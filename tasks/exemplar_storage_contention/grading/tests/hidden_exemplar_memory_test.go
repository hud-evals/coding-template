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

// TestExemplarMemoryPerStoredExemplar grades the ticket's memory bound the
// way the fleet's small servers feel it: for the same stored content, the new
// storage may keep at most ~25% more heap alive than the current one. The
// reference is a verbatim copy of the original implementation compiled into
// this binary (origExemplarStorage), fed the identical workload in the same
// process, so the bound is a ratio and not a machine-dependent byte count.
//
// Four shapes of content, all at the production default capacity and all with
// per-exemplar labels (a trace id is unique per exemplar in production, so
// whatever a design keeps alive for an exemplar it no longer stores is paid
// for in label memory):
//
//   - a steady mix: 2048 series, ~50 exemplars each;
//   - a storage full of quiet series: 100000 series holding one exemplar each,
//     which is what most of the fleet looks like, and where per-series
//     bookkeeping is the whole bill;
//   - the ticket's skew: 8 hot series producing 98% of the exemplars, 8192
//     cold ones the rest;
//   - the aftermath of a config-reload storm (shrink, grow, disable,
//     re-enable with appends running throughout), settled and refilled.
//
// A design that pads its entries to cache lines, keeps a large per-series
// record next to every index entry, or reclaims evicted exemplars lazily
// enough that a good part of a second buffer's worth of labels stays alive,
// lands well above the bound; the reference solution measures 1.00-1.06x.
func TestExemplarMemoryPerStoredExemplar(t *testing.T) {
	const (
		memCapacity   = 100000
		memMaxRatio   = 1.25
		memSlackBytes = 1 << 20 // absolute slack, for allocator granularity
	)

	type memStore interface {
		AddExemplar(l labels.Labels, e exemplar.Exemplar) error
		Resize(l int64) int
	}
	mkImpl := func() memStore {
		s, err := NewCircularExemplarStorage(memCapacity, NewExemplarMetrics(nil), 0)
		require.NoError(t, err)
		return s.(*CircularExemplarStorage)
	}
	mkOrig := func() memStore {
		s, err := newOrigExemplarStorage(memCapacity, newOrigMetrics(nil), 0)
		require.NoError(t, err)
		return s
	}

	traceLabels := func(k int64) labels.Labels {
		return labels.FromStrings("trace_id", fmt.Sprintf("%016x%08x", uint64(k)*0x9e3779b97f4a7c15, k))
	}
	mkSeries := func(name string, n int) []labels.Labels {
		out := make([]labels.Labels, n)
		for i := range out {
			out[i] = labels.FromStrings("__name__", name, "job", "j", "instance", fmt.Sprintf("i%d", i))
		}
		return out
	}
	// fill appends n exemplars round-robin over series, each with its own
	// labels, timestamps increasing per round.
	fill := func(s memStore, series []labels.Labels, n int, from int64) {
		ts := from
		k := 0
		for k < n {
			for i := range series {
				_ = s.AddExemplar(series[i], exemplar.Exemplar{Labels: traceLabels(ts*int64(len(series)) + int64(i)), Value: float64(ts), Ts: ts, HasTs: true})
				k++
				if k >= n {
					break
				}
			}
			ts++
		}
	}
	liveHeap := func(mk func() memStore, run func(memStore)) int64 {
		runtime.GC()
		runtime.GC()
		var before runtime.MemStats
		runtime.ReadMemStats(&before)
		s := mk()
		run(s)
		runtime.GC()
		runtime.GC()
		var after runtime.MemStats
		runtime.ReadMemStats(&after)
		runtime.KeepAlive(s)
		return int64(after.HeapAlloc) - int64(before.HeapAlloc)
	}

	// Series label sets are created up front so that they are part of the
	// baseline, not of what is attributed to the storage.
	uniform := mkSeries("mem_uniform", 2048)
	quiet := mkSeries("mem_quiet", memCapacity)
	hot := mkSeries("mem_hot", 8)
	cold := mkSeries("mem_cold", 8192)

	workloads := []struct {
		name string
		run  func(s memStore)
	}{
		{"steady_mix", func(s memStore) { fill(s, uniform, 2*memCapacity, 1) }},
		{"quiet_series", func(s memStore) { fill(s, quiet, 3*memCapacity, 1) }},
		{"hot_cold_skew", func(s memStore) {
			for k := range 10 * memCapacity {
				l := hot[k%len(hot)]
				if k%50 == 0 {
					l = cold[(k/50)%len(cold)]
				}
				_ = s.AddExemplar(l, exemplar.Exemplar{Labels: traceLabels(int64(k)), Value: float64(k), Ts: int64(k), HasTs: true})
			}
		}},
		{"after_reload_storm", func(s memStore) {
			var wg sync.WaitGroup
			stop := make(chan struct{})
			for w := range 4 {
				wg.Add(1)
				go func(w int) {
					defer wg.Done()
					mine := uniform[w*512 : (w+1)*512]
					ts := int64(1)
					for {
						select {
						case <-stop:
							return
						default:
						}
						for i, l := range mine {
							_ = s.AddExemplar(l, exemplar.Exemplar{Labels: traceLabels(ts*4096 + int64(w*512+i)), Value: float64(ts), Ts: ts, HasTs: true})
						}
						ts++
					}
				}(w)
			}
			sizes := []int64{50000, memCapacity, 8192, 0, 65536, memCapacity, 1000, memCapacity}
			for range 40 {
				for _, n := range sizes {
					s.Resize(n)
				}
			}
			close(stop)
			wg.Wait()
			s.Resize(memCapacity)
			fill(s, uniform, 2*memCapacity, 1<<40)
		}},
	}

	for _, w := range workloads {
		orig := liveHeap(mkOrig, w.run)
		impl := liveHeap(mkImpl, w.run)
		ratio := float64(impl) / float64(orig)
		fmt.Printf("MEMRATIO %-18s orig=%.1fMB impl=%.1fMB ratio=%.2f (bound %.2f)\n", w.name, float64(orig)/(1<<20), float64(impl)/(1<<20), ratio, memMaxRatio)
		require.LessOrEqualf(t, impl, int64(float64(orig)*memMaxRatio)+memSlackBytes,
			"for the same stored content (%s) the storage keeps %.1f MB of heap alive where the current implementation keeps %.1f MB (%.2fx, bound %.2fx). "+
				"Memory per stored exemplar and per series must stay within ~25%% of today's: padded entries, a large per-series record "+
				"next to the index entry, or evicted exemplars whose labels are reclaimed lazily all cost the fleet's small servers real memory.",
			w.name, float64(impl)/(1<<20), float64(orig)/(1<<20), ratio, memMaxRatio)
	}
}
