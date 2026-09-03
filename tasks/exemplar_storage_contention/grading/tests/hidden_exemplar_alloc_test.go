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
	"runtime"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
)

// TestExemplarAppendAllocationsAndMemory grades two resource bounds the
// ticket states for the append path at the production default capacity:
//
//  1. The steady-state append path (an in-order exemplar for a series the
//     storage already knows) must not allocate on the heap. The original
//     storage does not, and a throughput fix that turns every append into a
//     garbage-collector customer is not a throughput fix: on a busy server the
//     GC cost lands on every goroutine in the process, not just the appender.
//  2. Memory stays bounded under resize churn: after a config-reload storm
//     (shrink, grow, disable, re-enable, with appends running throughout) the
//     storage must not have retained old buffers, generations or per-append
//     bookkeeping. The live heap attributable to a full 100000-exemplar
//     storage must stay under a generous multiple of what the exemplars
//     themselves occupy.
func TestExemplarAppendAllocationsAndMemory(t *testing.T) {
	const (
		allocCapacity   = 100000
		allocSeries     = 2048
		allocRuns       = 20000
		allocWriters    = 4
		allocChurnLoops = 60
		// A stored exemplar is ~64-80 bytes (labels handle, value, timestamp,
		// list links, index reference); 100000 of them are ~8 MB, and the
		// series index a few hundred KB more. 48 MB is six times that.
		memBoundBytes = 48 << 20
	)

	series := make([]labels.Labels, allocSeries)
	for s := range series {
		series[s] = labels.FromStrings("__name__", "alloc_metric", "job", "j", "instance", fmt.Sprintf("i%d", s))
	}
	exLabels := labels.FromStrings("trace_id", "0123456789abcdef")

	fill := func(es ExemplarStorage, from int64, n int) int64 {
		ts := from
		k := 0
		for k < n {
			for s := range series {
				_ = es.AddExemplar(series[s], exemplar.Exemplar{Labels: exLabels, Value: float64(ts), Ts: ts})
				k++
				if k >= n {
					break
				}
			}
			ts++
		}
		return ts
	}

	// ── 1. Zero allocations per steady-state append ────────────────────────
	{
		store, err := NewCircularExemplarStorage(allocCapacity, NewExemplarMetrics(nil), 0)
		require.NoError(t, err)
		// Wrap the buffer twice so every series is known and every slot has
		// been evicted at least once: this is the steady state, where the index
		// is stable and eviction bookkeeping runs on every append.
		ts := fill(store, 1, 2*allocCapacity)

		k := 0
		var addErr error
		allocs := testing.AllocsPerRun(allocRuns, func() {
			if err := store.AddExemplar(series[k%allocSeries], exemplar.Exemplar{Labels: exLabels, Value: float64(ts), Ts: ts}); err != nil {
				addErr = err
			}
			k++
			if k%allocSeries == 0 {
				ts++
			}
		})
		require.NoError(t, addErr)
		fmt.Printf("ALLOC steady_state_appends allocs_per_append=%.0f\n", allocs)
		require.Zerof(t, allocs,
			"the steady-state append path allocates %.0f heap object(s) per exemplar; the original storage allocates none. "+
				"Every append becoming a GC customer is a throughput regression for the whole process, not just the appender.", allocs)
	}

	// ── 2. Bounded memory under resize churn ───────────────────────────────
	{
		runtime.GC()
		var before runtime.MemStats
		runtime.ReadMemStats(&before)

		store, err := NewCircularExemplarStorage(allocCapacity, NewExemplarMetrics(nil), 0)
		require.NoError(t, err)
		es := store.(*CircularExemplarStorage)

		var wg sync.WaitGroup
		stop := make(chan struct{})
		for w := range allocWriters {
			wg.Add(1)
			go func(w int) {
				defer wg.Done()
				mine := series[w*(allocSeries/allocWriters) : (w+1)*(allocSeries/allocWriters)]
				ts := int64(1)
				for {
					select {
					case <-stop:
						return
					default:
					}
					for _, l := range mine {
						_ = es.AddExemplar(l, exemplar.Exemplar{Labels: exLabels, Value: float64(ts), Ts: ts})
					}
					ts++
				}
			}(w)
		}
		sizes := []int64{50000, allocCapacity, 8192, 0, 65536, allocCapacity, 1000, allocCapacity}
		for range allocChurnLoops {
			for _, n := range sizes {
				es.Resize(n)
			}
		}
		close(stop)
		wg.Wait()

		// Settle at full capacity, fill it completely, then measure what the
		// storage keeps alive.
		es.Resize(allocCapacity)
		fill(es, 1<<40, 2*allocCapacity)

		runtime.GC()
		var after runtime.MemStats
		runtime.ReadMemStats(&after)
		live := int64(after.HeapAlloc) - int64(before.HeapAlloc)
		fmt.Printf("MEM live_heap_delta_bytes=%d bound=%d (%.1f MB vs %.0f MB)\n", live, memBoundBytes, float64(live)/(1<<20), float64(memBoundBytes)/(1<<20))
		require.LessOrEqualf(t, live, int64(memBoundBytes),
			"after a resize storm a full %d-exemplar storage keeps %.1f MB of heap alive (bound %.0f MB): "+
				"memory must stay proportional to max_exemplars, not to the number of resizes or appends seen",
			allocCapacity, float64(live)/(1<<20), float64(memBoundBytes)/(1<<20))
		runtime.KeepAlive(es)
	}
}
