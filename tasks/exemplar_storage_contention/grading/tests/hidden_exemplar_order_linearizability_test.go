// Copyright 2025 The Prometheus Authors
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package tsdb

import (
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
)

// TestExemplarIngestionOrderIsLinearizable pins IterateExemplars' documented
// contract - every stored exemplar, oldest to newest in ingestion order across
// the whole storage - under the one workload where "ingestion order" is not
// simply "whatever order one goroutine appended in": several goroutines
// appending to the SAME series at once (remote-write receivers and OTLP
// ingestion do this), so that a large share of appends are rejected as
// out-of-order after they have already started.
//
// The test does not need to know which interleaving the storage chose. It
// checks the two things any linearizable ingestion order must satisfy:
//
//  1. Real-time order: every append that completed before a barrier is older
//     than every append that started after it. After the barrier the walk must
//     yield all "phase A" exemplars before the first "phase B" exemplar.
//  2. Per-series order: restricted to any one series the walk is in the order
//     that series' exemplars were accepted, which (with a zero out-of-order
//     window and unique timestamps) is timestamp order.
//
// The classic way to break both is an append that reserves its place in the
// storage BEFORE it is finally accepted or rejected, and cannot give the place
// back: the slot then keeps an exemplar from a whole buffer cycle ago sitting
// among the newest ones. That only shows up under contention with rejections,
// which the concurrency tests with disjoint per-goroutine series never create.
//
// Phase A also runs a paced config-reload resize storm (shrink, grow, disable,
// re-enable), because the order has to survive migration too. The capacity
// bound, the usable-budget bound and a snapshot -> replay-into-smaller-buffer
// round trip are re-checked at the end. Run with -race.
func TestExemplarIngestionOrderIsLinearizable(t *testing.T) {
	const (
		linCapacity  = 100000
		linReplayCap = 50000
		linWriters   = 8
		linSeries    = 2048
		linRoundsA1  = 40 // with the resize storm
		linPhaseB    = 50000
		linPhaseBTs  = int64(1 << 40)
	)

	store, err := NewCircularExemplarStorage(linCapacity, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	es := store.(*CircularExemplarStorage)

	series := make([]labels.Labels, linSeries)
	for s := range series {
		series[s] = labels.FromStrings("__name__", "lin", "s", fmt.Sprintf("%d", s))
	}
	exLabels := labels.FromStrings("trace_id", "linearizable")

	// Every writer walks the same series in the same order; writer w uses
	// timestamp round*linWriters+w, so timestamps are unique per series and the
	// writers constantly race each other on the same series, with whichever
	// one arrives late being rejected as out of order.
	runRounds := func(from, to int, base int64, accepted *atomic.Int64, limit int64) {
		var wg sync.WaitGroup
		for w := range linWriters {
			wg.Add(1)
			go func(w int) {
				defer wg.Done()
				for r := from; r < to; r++ {
					ts := base + int64(r*linWriters+w)
					for s := range series {
						if limit > 0 && accepted.Load() >= limit {
							return
						}
						if err := es.AddExemplar(series[s], exemplar.Exemplar{Labels: exLabels, Value: float64(ts), Ts: ts}); err == nil && accepted != nil {
							accepted.Add(1)
						}
					}
				}
			}(w)
		}
		wg.Wait()
	}

	// Background readers: queries and full walks alongside everything else.
	stop := make(chan struct{})
	var wgBackground sync.WaitGroup
	wgBackground.Add(1)
	go func() {
		defer wgBackground.Done()
		m := []*labels.Matcher{labels.MustNewMatcher(labels.MatchEqual, "__name__", "lin")}
		for {
			select {
			case <-stop:
				return
			case <-time.After(5 * time.Millisecond):
			}
			_, _ = es.Select(0, 1<<62, m)
			_ = es.IterateExemplars(func(labels.Labels, exemplar.Exemplar) error { return nil })
		}
	}()

	// ── Phase A1: contended appends under a resize storm ───────────────────
	stormDone := make(chan struct{})
	wgBackground.Add(1)
	go func() {
		defer wgBackground.Done()
		sizes := []int64{linCapacity, 65536, 50000, 8192, 0, 100, 65536, linCapacity}
		for {
			for _, n := range sizes {
				select {
				case <-stormDone:
					return
				case <-time.After(time.Millisecond):
				}
				es.Resize(n)
			}
		}
	}()
	runRounds(0, linRoundsA1, 0, nil, 0)
	close(stormDone)

	// ── Phase A2: contended appends at full capacity ──────────────────────
	es.Resize(linCapacity)
	var acceptedA atomic.Int64
	runRounds(linRoundsA1, 1<<20, 0, &acceptedA, 2*linCapacity)
	require.GreaterOrEqualf(t, acceptedA.Load(), int64(2*linCapacity),
		"phase A accepted only %d appends; the buffer did not wrap", acceptedA.Load())

	// ── Barrier: every phase A append has returned. ───────────────────────

	// ── Phase B: contended appends, all newer than anything in phase A ────
	var acceptedB atomic.Int64
	runRounds(0, 1<<20, linPhaseBTs, &acceptedB, linPhaseB)
	nB := acceptedB.Load()
	require.GreaterOrEqual(t, nB, int64(linPhaseB))
	require.Less(t, nB, int64(linPhaseB+linWriters*2))

	close(stop)
	wgBackground.Wait()

	// ── The walk ─────────────────────────────────────────────────────────
	type entry struct {
		l labels.Labels
		e exemplar.Exemplar
	}
	var got []entry
	require.NoError(t, es.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		got = append(got, entry{l, e})
		return nil
	}))
	n := len(got)
	fmt.Printf("ORDER walked=%d accepted_B=%d\n", n, nB)

	require.LessOrEqualf(t, n, linCapacity,
		"IterateExemplars returned %d exemplars with a configured capacity of %d: the capacity bound was not honoured", n, linCapacity)
	require.GreaterOrEqualf(t, n, int(0.9*linCapacity),
		"the storage retains %d exemplars out of a budgeted capacity of %d after sustained ingestion; the budget must be usable", n, linCapacity)

	// 1. Real-time order across the barrier.
	firstB := -1
	seenB := 0
	for i, en := range got {
		if en.e.Ts >= linPhaseBTs {
			if firstB == -1 {
				firstB = i
			}
			seenB++
			continue
		}
		require.Equalf(t, -1, firstB,
			"IterateExemplars order is not ingestion order: an exemplar whose append completed before the barrier "+
				"(series %s, ts %d) was yielded at position %d, after exemplars appended after the barrier (first at position %d). "+
				"An append that reserves its place in the storage before it is finally accepted or rejected must not leave an older "+
				"exemplar sitting in a newer position.", en.l.String(), en.e.Ts, i, firstB)
	}
	require.NotEqual(t, -1, firstB, "no phase B exemplar was retained")
	require.GreaterOrEqualf(t, seenB, int(0.95*float64(nB)),
		"only %d of the %d exemplars accepted after the barrier are still stored, although only %d were accepted and the capacity is %d",
		seenB, nB, nB, linCapacity)

	// 2. Per-series order within the walk, and the per-series order Select
	//    reports, are both accepted-timestamp order.
	lastTs := make(map[string]int64, linSeries)
	for i, en := range got {
		key := en.l.String()
		if prev, ok := lastTs[key]; ok {
			require.Greaterf(t, en.e.Ts, prev,
				"IterateExemplars yielded series %s out of its own ingestion order at position %d: ts %d after ts %d", key, i, en.e.Ts, prev)
		}
		lastTs[key] = en.e.Ts
	}
	m := []*labels.Matcher{labels.MustNewMatcher(labels.MatchEqual, "__name__", "lin")}
	res, err := es.Select(0, 1<<62, m)
	require.NoError(t, err)
	total := 0
	for _, qr := range res {
		for i := 1; i < len(qr.Exemplars); i++ {
			require.Lessf(t, qr.Exemplars[i-1].Ts, qr.Exemplars[i].Ts,
				"series %s returned exemplars out of ingestion order: %d after %d", qr.SeriesLabels.String(), qr.Exemplars[i].Ts, qr.Exemplars[i-1].Ts)
		}
		total += len(qr.Exemplars)
	}
	require.Equalf(t, n, total, "Select sees %d exemplars but IterateExemplars yielded %d", total, n)

	// 3. Snapshot -> replay into a smaller buffer keeps the newest.
	replayStore, err := NewCircularExemplarStorage(linReplayCap, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	replay := replayStore.(*CircularExemplarStorage)
	require.NoError(t, es.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		return replay.AddExemplar(l, e)
	}), "replaying a snapshot into a smaller storage must not fail")
	kept := map[string]struct{}{}
	keyOf := func(l labels.Labels, e exemplar.Exemplar) string { return fmt.Sprintf("%s|%d", l.String(), e.Ts) }
	keptCount := 0
	require.NoError(t, replay.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		kept[keyOf(l, e)] = struct{}{}
		keptCount++
		return nil
	}))
	require.LessOrEqual(t, keptCount, linReplayCap)
	for _, en := range got[n-(n*2)/5:] {
		if _, ok := kept[keyOf(en.l, en.e)]; !ok {
			t.Fatalf("replaying the snapshot into a half-sized buffer lost a RECENT exemplar (series %s, ts %d, newest 40%% of the snapshot)", en.l.String(), en.e.Ts)
		}
	}
	for _, en := range got[:(n*2)/5] {
		if _, ok := kept[keyOf(en.l, en.e)]; ok {
			t.Fatalf("replaying the snapshot into a half-sized buffer kept an OLD exemplar (series %s, ts %d, oldest 40%% of the snapshot)", en.l.String(), en.e.Ts)
		}
	}
}
