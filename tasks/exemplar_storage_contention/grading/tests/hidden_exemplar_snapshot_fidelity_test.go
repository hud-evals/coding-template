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
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
)

// TestExemplarSnapshotReplayFidelity checks the consumer contract the
// chunk-snapshot path depends on, at the production default capacity
// (max_exemplars: 100000):
//
//  1. IterateExemplars keeps its documented contract - "from oldest to newest
//     appended" - across the WHOLE storage, not merely within some internal
//     partition.
//  2. As a consequence, a snapshot written in that order and replayed into a
//     SMALLER buffer (a server restarted with a reduced max_exemplars, which
//     replays exemplars through AddExemplar exactly like tsdb/head_wal.go
//     does) retains the newest exemplars, not an arbitrary subset.
//  3. The configured capacity stays a hard upper bound, and after sustained
//     ingestion the storage actually holds approximately the capacity it was
//     budgeted (we allow a few percent of slack for internal partitioning).
//
// Run it with -race: the first half of the test is a sustained mixed workload
// (concurrent appends, a config-reload resize storm, queries and full walks)
// at production capacity, which is where partitioned designs earn or lose
// their keep.
func TestExemplarSnapshotReplayFidelity(t *testing.T) {
	const (
		fidCapacity     = 100000
		fidReplayCap    = 50000
		fidWriters      = 8
		fidSeriesPerWkr = 256
		fidChurnAppends = 250000 // per writer, phase 1
		fidSeqSeries    = 2048
		fidSeqAppends   = 200000 // phase 2, twice the capacity
		fidPhase2Base   = int64(1 << 40)
	)

	store, err := NewCircularExemplarStorage(fidCapacity, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	es := store.(*CircularExemplarStorage)

	// ── Phase 1: sustained mixed load at production capacity ────────────────
	churnSeries := func(w, s int) labels.Labels {
		return labels.FromStrings("__name__", "churn", "w", fmt.Sprintf("%d", w), "s", fmt.Sprintf("%d", s))
	}

	var wgWriters, wgBackground sync.WaitGroup
	stop := make(chan struct{})

	for w := range fidWriters {
		wgWriters.Add(1)
		go func(w int) {
			defer wgWriters.Done()
			exLabels := labels.FromStrings("trace_id", fmt.Sprintf("w%d", w))
			ts := int64(1)
			n := 0
			for n < fidChurnAppends {
				for s := range fidSeriesPerWkr {
					// Errors are expected while the resizer passes through the
					// disabled state; corruption is not.
					_ = es.AddExemplar(churnSeries(w, s), exemplar.Exemplar{Labels: exLabels, Value: float64(ts), Ts: ts})
					n++
					if n >= fidChurnAppends {
						break
					}
				}
				ts++
			}
		}(w)
	}

	// Like the reader below, the resizer is paced rather than free-running: a
	// resize at this capacity migrates up to 100k entries, and a back-to-back
	// storm of them starves a serialized implementation into this test's
	// timeout instead of letting it reach a verdict. ~1000 resizes/minute is
	// still far beyond any real config-reload rate and keeps every gate
	// crossing (sharded <-> unsharded <-> disabled) hot under -race.
	wgBackground.Add(1)
	go func() {
		defer wgBackground.Done()
		sizes := []int64{fidCapacity, 65536, 50000, 8192, 0, 100, 65536, fidCapacity}
		for {
			for _, n := range sizes {
				select {
				case <-stop:
					return
				case <-time.After(time.Millisecond):
				}
				es.Resize(n)
			}
		}
	}()

	// The reader walks periodically rather than continuously: back-to-back
	// full walks starve a serialized implementation so badly that this test
	// would time out instead of reaching its verdict. Punishing serialization
	// is the scalability and walk-contention criteria's job; this test's job
	// is fidelity, so it only needs walks to INTERLEAVE with appends and
	// resizes, not to dominate them.
	wgBackground.Add(1)
	go func() {
		defer wgBackground.Done()
		m := []*labels.Matcher{labels.MustNewMatcher(labels.MatchEqual, "__name__", "churn")}
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

	wgWriters.Wait()
	close(stop)
	wgBackground.Wait()

	// ── Phase 2: deterministic sequential fill ──────────────────────────────
	// A single goroutine appends twice the capacity of fresh exemplars with a
	// globally unique, strictly increasing timestamp per append. Ingestion
	// order is therefore known exactly: it is timestamp order.
	es.Resize(fidCapacity)

	seqSeries := make([]labels.Labels, fidSeqSeries)
	for s := range seqSeries {
		seqSeries[s] = labels.FromStrings("__name__", "fid", "s", fmt.Sprintf("%d", s))
	}
	exLabels := labels.FromStrings("trace_id", "fidelity")
	for k := range fidSeqAppends {
		ts := fidPhase2Base + int64(k)
		require.NoError(t, es.AddExemplar(seqSeries[k%fidSeqSeries], exemplar.Exemplar{Labels: exLabels, Value: float64(k), Ts: ts}),
			"sequential append %d failed", k)
	}

	// ── Check 1: iteration order is global ingestion order ──────────────────
	type entry struct {
		l labels.Labels
		e exemplar.Exemplar
	}
	var got []entry
	require.NoError(t, es.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		got = append(got, entry{l, e})
		return nil
	}))

	require.LessOrEqualf(t, len(got), fidCapacity,
		"IterateExemplars returned %d exemplars with a configured capacity of %d: the capacity bound was not honoured",
		len(got), fidCapacity)
	require.GreaterOrEqualf(t, len(got), int(0.9*fidCapacity),
		"the storage retains %d exemplars out of a budgeted capacity of %d after ingesting %d fresh ones; "+
			"the configured budget is expected to be usable (a few percent of internal slack is fine, %d%% is not)",
		len(got), fidCapacity, fidSeqAppends, 100-100*len(got)/fidCapacity)

	firstPhase2 := -1
	prevTs := int64(0)
	for i, en := range got {
		if en.e.Ts < fidPhase2Base {
			require.Equalf(t, -1, firstPhase2,
				"IterateExemplars order violates its oldest-to-newest contract: an exemplar ingested before the "+
					"sequential phase (ts=%d) was yielded at position %d, AFTER exemplars ingested later (first at position %d). "+
					"The chunk-snapshot writer depends on global ingestion order.", en.e.Ts, i, firstPhase2)
			continue
		}
		if firstPhase2 == -1 {
			firstPhase2 = i
		} else {
			require.GreaterOrEqualf(t, en.e.Ts, prevTs,
				"IterateExemplars order violates its oldest-to-newest contract within the sequential phase: "+
					"ts=%d yielded after ts=%d (position %d). Sequential ingestion order is timestamp order here.",
				en.e.Ts, prevTs, i)
		}
		prevTs = en.e.Ts
	}
	require.NotEqual(t, -1, firstPhase2, "no exemplar from the sequential phase was retained; the storage lost recent data")

	// ── Check 2: snapshot replayed into a smaller buffer keeps the newest ───
	replayStore, err := NewCircularExemplarStorage(fidReplayCap, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	replay := replayStore.(*CircularExemplarStorage)

	require.NoError(t, es.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		return replay.AddExemplar(l, e)
	}), "replaying a snapshot into a smaller storage must not fail: the WAL replay path feeds exemplars back through AddExemplar in snapshot order")

	kept := map[string]struct{}{}
	keyOf := func(l labels.Labels, e exemplar.Exemplar) string {
		return fmt.Sprintf("%s|%d|%g", l.String(), e.Ts, e.Value)
	}
	var keptCount int
	require.NoError(t, replay.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		kept[keyOf(l, e)] = struct{}{}
		keptCount++
		return nil
	}))
	require.LessOrEqualf(t, keptCount, fidReplayCap,
		"after replay the smaller storage holds %d exemplars with a configured capacity of %d", keptCount, fidReplayCap)

	// The replayed storage has half the capacity, so it must have kept
	// (approximately) the newest half of the snapshot. Allow generous slack
	// for internal partitioning: everything in the newest 40% must survive,
	// nothing from the oldest 40% may.
	n := len(got)
	for _, en := range got[n-(n*2)/5:] {
		if _, ok := kept[keyOf(en.l, en.e)]; !ok {
			t.Fatalf("replaying a snapshot into a smaller buffer lost a RECENT exemplar (series %s, ts %d, newest 40%% of the snapshot). "+
				"After a restart with a reduced max_exemplars the storage must retain the newest exemplars, not an arbitrary subset "+
				"- this is decided by the order IterateExemplars yields them for the snapshot.", en.l.String(), en.e.Ts)
		}
	}
	for _, en := range got[:(n*2)/5] {
		if _, ok := kept[keyOf(en.l, en.e)]; ok {
			t.Fatalf("replaying a snapshot into a half-sized buffer kept an OLD exemplar (series %s, ts %d, oldest 40%% of the snapshot) "+
				"- which means a newer one was evicted to make room for it. Snapshot order must be global ingestion order.",
				en.l.String(), en.e.Ts)
		}
	}
}
