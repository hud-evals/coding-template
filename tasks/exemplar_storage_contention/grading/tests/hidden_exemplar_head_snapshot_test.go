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
	"context"
	"fmt"
	"math"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/tsdb/wlog"
	"github.com/prometheus/prometheus/util/compression"
)

// TestHeadChunkSnapshotExemplarsRoundTrip is the end-to-end version of the
// snapshot contract, through the Head rather than the storage alone: exemplars
// ingested through concurrent Head appenders at the production default
// max_exemplars, persisted by the chunk-snapshot writer on shutdown (which
// walks the storage with IterateExemplars) and fed back through AddExemplar by
// the snapshot replay on restart, must come back as the same sequence - same
// exemplars, same order, possibly minus some of the oldest ones lost on the
// way in - that IterateExemplars reported before shutdown.
//
// The repo's own TestChunkSnapshot checks this with ten series and a few
// hundred exemplars, far below any capacity or partitioning threshold; this
// one runs it at the operating point the ticket names.
func TestHeadChunkSnapshotExemplarsRoundTrip(t *testing.T) {
	const (
		e2eSeries    = 1024
		e2eWriters   = 8
		e2eExemplars = 160000 // total, 1.6x the production default capacity
		e2eBatch     = 512
	)

	opts := newTestHeadDefaultOptions(1000, false)
	opts.EnableMemorySnapshotOnShutdown = true
	head, _ := newTestHeadWithOptions(t, compression.None, opts)
	capacity := int(opts.MaxExemplars.Load())
	require.Equal(t, 100000, capacity, "the test expects the production default max_exemplars")

	// Create the series.
	seriesLabels := make([]labels.Labels, e2eSeries)
	seriesRefs := make([]storage.SeriesRef, e2eSeries)
	{
		app := head.Appender(context.Background())
		for s := range seriesLabels {
			seriesLabels[s] = labels.FromStrings("__name__", "e2e_metric", "instance", fmt.Sprintf("i%d", s))
			ref, err := app.Append(0, seriesLabels[s], 1, 1)
			require.NoError(t, err)
			seriesRefs[s] = ref
		}
		require.NoError(t, app.Commit())
	}

	// Ingest exemplars through concurrent Head appenders, each on its own
	// series, committing in batches like a scrape loop does.
	perWriter := e2eExemplars / e2eWriters
	errCh := make(chan error, e2eWriters)
	var wg sync.WaitGroup
	for w := range e2eWriters {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			mine := seriesLabels[w*(e2eSeries/e2eWriters) : (w+1)*(e2eSeries/e2eWriters)]
			refs := seriesRefs[w*(e2eSeries/e2eWriters) : (w+1)*(e2eSeries/e2eWriters)]
			app := head.Appender(context.Background())
			inBatch := 0
			ts := int64(1000)
			for n := 0; n < perWriter; {
				for s := range mine {
					e := exemplar.Exemplar{
						Labels: labels.FromStrings("trace_id", fmt.Sprintf("w%d-%d", w, ts)),
						Value:  float64(ts),
						Ts:     ts,
						HasTs:  true,
					}
					if _, err := app.AppendExemplar(refs[s], mine[s], e); err != nil {
						errCh <- fmt.Errorf("writer %d: AppendExemplar: %w", w, err)
						return
					}
					n++
					inBatch++
					if inBatch >= e2eBatch {
						if err := app.Commit(); err != nil {
							errCh <- fmt.Errorf("writer %d: Commit: %w", w, err)
							return
						}
						app = head.Appender(context.Background())
						inBatch = 0
					}
					if n >= perWriter {
						break
					}
				}
				ts++
			}
			if err := app.Commit(); err != nil {
				errCh <- fmt.Errorf("writer %d: final Commit: %w", w, err)
			}
		}(w)
	}
	wg.Wait()
	close(errCh)
	for err := range errCh {
		require.NoError(t, err)
	}

	type ex struct {
		series string
		ts     int64
		value  float64
		labels string
	}
	walk := func() []ex {
		var out []ex
		require.NoError(t, head.exemplars.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
			out = append(out, ex{l.String(), e.Ts, e.Value, e.Labels.String()})
			return nil
		}))
		return out
	}

	before := walk()
	fmt.Printf("E2E before_snapshot=%d capacity=%d\n", len(before), capacity)
	require.LessOrEqual(t, len(before), capacity, "capacity bound violated before the snapshot")
	require.GreaterOrEqualf(t, len(before), int(0.9*float64(capacity)),
		"after ingesting %d exemplars the storage holds %d of a budgeted %d", e2eExemplars, len(before), capacity)

	// Shut down (writes the chunk snapshot) and restart (replays it).
	require.NoError(t, head.Close())
	w, err := wlog.NewSize(nil, nil, head.wal.Dir(), 32768, compression.None)
	require.NoError(t, err)
	head, err = NewHead(nil, nil, w, nil, head.opts, nil)
	require.NoError(t, err)
	require.NoError(t, head.Init(math.MinInt64))
	t.Cleanup(func() { _ = head.Close() })

	after := walk()
	fmt.Printf("E2E after_replay=%d\n", len(after))
	require.LessOrEqual(t, len(after), capacity, "capacity bound violated after the replay")
	// A design that balances capacity between partitions by measured
	// ingestion rate re-learns the layout on the way in and drops some of the
	// oldest exemplars until it has (the reference solution comes back with
	// 79-98% depending on how bursty the scheduling of the writers was). What
	// must hold regardless is the order: nothing reordered, duplicated or
	// invented. The retention floor here only catches a replay that discards
	// wholesale.
	require.GreaterOrEqualf(t, len(after), int(0.50*float64(len(before))),
		"the chunk snapshot persisted %d exemplars but only %d came back after restart: the snapshot/replay round trip lost exemplars",
		len(before), len(after))

	// What came back must be the persisted sequence, in the persisted order:
	// the replayed walk is a subsequence of the pre-restart walk.
	j := 0
	for i := range after {
		for j < len(before) && before[j] != after[i] {
			j++
		}
		if j == len(before) {
			t.Fatalf("exemplar #%d after the restart (%+v) is not in the persisted sequence, or not in the persisted order. "+
				"The chunk-snapshot writer persists exemplars in IterateExemplars order and the replay feeds them back through AddExemplar "+
				"in that order; the storage must reproduce the same exemplars in the same order.", i, after[i])
		}
		j++
	}
}
