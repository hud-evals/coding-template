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
	"errors"
	"fmt"
	"runtime"
	"sync"
	"testing"
	"time"
	"unicode/utf8"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/storage"
)

// TestExemplarIngestionScalability grades the ticket's actual objective:
// more total exemplar ingestion throughput on many-core servers, without
// making every append slower to get it.
//
// It benchmarks the storage under test against a reference copy of the
// ORIGINAL single-lock implementation compiled into this very test binary
// (see refExemplarStorage below), so the comparison is machine-independent:
// both run in the same process, on the same series shapes, at the same
// capacity (the production default of 100000).
//
// Two ratios are required, both stated in the ticket:
//
//   - single appender: impl must reach at least minSingleRatio (0.80) of the
//     reference's single-threaded throughput. Buying parallelism by taxing
//     the uncontended path ~2x is not solving a throughput ticket. The
//     reference solution measures 0.96-1.0 here (best of 5, 2 vCPUs); the
//     make-appends-expensive class measures 0.55-0.62.
//   - parallel appenders (G = min(8, GOMAXPROCS), disjoint series): impl
//     must reach at least minParallelScaling times its OWN single-threaded
//     throughput. The reference storage is NEGATIVE here (parallel is slower
//     than serial); any real fix is comfortably positive. Only asserted with
//     6 or more CPUs (see below); the value is logged regardless.
//
// The thresholds are below what the reference solution achieves (measured:
// single ratio 0.92-1.05x at 2 vCPUs over 14 runs, parallel scaling
// 1.5-1.7x at 8 workers on a 22-CPU host) and above what a storage-wide or
// slot-serialized design achieves (single 0.55-0.62x for the
// make-appends-expensive class; scaling <=1.05x for serialized designs).
const (
	scalCapacity     = 100000
	// The single-appender floor is measured at a capacity whose working set
	// fits mid-size CPU caches. At 100k a sharded design pays a pure
	// cache-footprint tax on small-cache cloud cores that has nothing to do
	// with its append-path cost (measured on the grading platform: gold
	// 0.63 at 100k but 0.92 at 32k, while the make-appends-expensive class
	// stays flat at 0.57-0.60 across capacities — its cost is intrinsic).
	// 32k separates the two effects; the floor below is about the append
	// path, not memory layout.
	scalSingleCap    = 32768
	scalSeriesPerWkr = 512
	scalSingleOps    = 1 << 21
	scalOpsPerWorker = 1 << 20
	scalRounds       = 5
	minSingleRatio   = 0.80
)

func scalSeries(w, s int) labels.Labels {
	return labels.FromStrings("__name__", "scrape_target", "job", fmt.Sprintf("j%d", w), "instance", fmt.Sprintf("i%d", s))
}

// scalAppender abstracts over the storage under test and the compiled-in
// reference implementation.
type scalAppender interface {
	AddExemplar(l labels.Labels, e exemplar.Exemplar) error
}

// scalRun appends ops exemplars from each of `workers` goroutines, each over
// its own disjoint series set, and returns total appends/sec. The buffer is
// wrapped once before timing starts so measurement is steady state.
func scalRun(t *testing.T, store scalAppender, capacity, workers, ops int, startTs int64) float64 {
	t.Helper()

	series := make([][]labels.Labels, workers)
	for w := range series {
		series[w] = make([]labels.Labels, scalSeriesPerWkr)
		for s := range series[w] {
			series[w][s] = scalSeries(w, s)
		}
	}
	exLabels := labels.FromStrings("trace_id", "0123456789abcdef")

	warm := capacity/(workers*scalSeriesPerWkr) + 2
	ts := startTs
	for range warm {
		for w := range workers {
			for s := range scalSeriesPerWkr {
				_ = store.AddExemplar(series[w][s], exemplar.Exemplar{Labels: exLabels, Value: 1, Ts: ts})
			}
		}
		ts++
	}

	errCh := make(chan error, workers)
	var wg sync.WaitGroup
	start := time.Now()
	for w := range workers {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			myTs := ts
			n := 0
			for n < ops {
				for s := range scalSeriesPerWkr {
					if err := store.AddExemplar(series[w][s], exemplar.Exemplar{Labels: exLabels, Value: float64(myTs), Ts: myTs}); err != nil {
						errCh <- fmt.Errorf("worker %d ts %d: %w", w, myTs, err)
						return
					}
					n++
					if n >= ops {
						break
					}
				}
				myTs++
			}
		}(w)
	}
	wg.Wait()
	elapsed := time.Since(start)
	close(errCh)
	for err := range errCh {
		require.NoError(t, err, "append failed during throughput measurement")
	}
	return float64(workers*ops) / elapsed.Seconds()
}


func TestExemplarIngestionScalability(t *testing.T) {
	gomax := runtime.GOMAXPROCS(0)
	workers := gomax
	if workers > 8 {
		workers = 8
	}
	require.GreaterOrEqualf(t, workers, 2,
		"grading environment has GOMAXPROCS=%d; at least 2 CPUs are required to measure parallel scaling", gomax)
	// The bar is set below the reference solution (1.5-1.7x at 8 workers on
	// 22 CPUs) and above every serialized design measured (all of which land
	// at or below ~1.05x, i.e. zero or negative scaling).
	//
	// Enforced slightly below the ticket's "~1.5x": in-container recalibration
	// saw gold runs dip to 1.42-1.44x under scheduler noise while every
	// serialized design stayed at or below ~1.05x, so 1.35 keeps a real
	// fail-side margin without flaking against correct solutions.
	//
	// Below 6 CPUs the scaling assertion is SKIPPED entirely: the grading
	// container is one physical core with two hyperthreads (Xeon Platinum
	// 8259CL, nproc=2), where the quantity is structurally unmeasurable (even
	// the reference solution measures ~0.9-1.0x there), and "4 CPUs" on the
	// same class of host is two cores. Discrimination survives on such hosts
	// because the clever-but-slower family fails the CPU-count-independent
	// single-appender floor (measured 0.55-0.62 at 2 CPUs vs the reference
	// solution's 0.92-0.99) and serialized designs fail the walk blocker.
	// On cloud hosts "4 CPUs" is two physical cores with hyperthreading, where
	// even the reference solution only measures ~1.1-1.15x with 4 workers; the
	// assertion is therefore only made from 6 CPUs up (measured on 22 CPUs:
	// reference solution 1.44-1.73x, sharded-but-serialized designs <=1.05x).
	minParallelScaling := 1.35
	checkScaling := workers >= 6

	mkImplAt := func(capacity int) scalAppender {
		store, err := NewCircularExemplarStorage(int64(capacity), NewExemplarMetrics(nil), 0)
		require.NoError(t, err)
		return store
	}
	mkRefAt := func(capacity int) scalAppender { return newRefExemplarStorage(int64(capacity)) }
	mkImpl := func() scalAppender { return mkImplAt(scalCapacity) }

	// Rounds are interleaved (ref, impl, parallel, ref, impl, parallel, ...)
	// and the best of each is kept, so a transient machine-wide slowdown biases
	// all three measurements alike instead of skewing one ratio.
	//
	// The floor pair runs at scalSingleCap (see the constant's comment); the
	// scaling pair runs at production capacity, and is only measured where it
	// will be asserted (>=4 CPUs) — implSingle at scalCapacity exists solely
	// as the scaling denominator so the ratio compares like with like.
	var refSingle, implSingle, implSingleProd, implParallel float64
	for r := range scalRounds {
		base := int64(1000 * (r + 1))
		if v := scalRun(t, mkRefAt(scalSingleCap), scalSingleCap, 1, scalSingleOps, base); v > refSingle {
			refSingle = v
		}
		if v := scalRun(t, mkImplAt(scalSingleCap), scalSingleCap, 1, scalSingleOps, base); v > implSingle {
			implSingle = v
		}
		if checkScaling {
			if v := scalRun(t, mkImpl(), scalCapacity, 1, scalSingleOps, base); v > implSingleProd {
				implSingleProd = v
			}
			if v := scalRun(t, mkImpl(), scalCapacity, workers, scalOpsPerWorker, base); v > implParallel {
				implParallel = v
			}
		}
	}

	singleRatio := implSingle / refSingle
	parallelScaling := 0.0
	if checkScaling {
		parallelScaling = implParallel / implSingleProd
	}

	fmt.Printf("SCALABILITY ref_single=%.0f/s impl_single=%.0f/s impl_parallel(%d)=%.0f/s single_ratio=%.3f parallel_scaling=%.3f\n",
		refSingle, implSingle, workers, implParallel, singleRatio, parallelScaling)

	require.GreaterOrEqualf(t, singleRatio, minSingleRatio,
		"uncontended appends regressed too far: %.0f/s vs %.0f/s for the original storage (%.2fx, need >= %.2fx). "+
			"The ticket requires keeping single-appender cost within ~20%% of the original.",
		implSingle, refSingle, singleRatio, minSingleRatio)
	if checkScaling {
		require.GreaterOrEqualf(t, parallelScaling, minParallelScaling,
			"appends do not scale with cores: %d parallel appenders reach %.0f/s vs %.0f/s for one appender "+
				"(%.2fx, need >= %.2fx). Appends for different series still serialize against each other.",
			workers, implParallel, implSingle, parallelScaling, minParallelScaling)
	} else {
		t.Logf("parallel-scaling assertion skipped: GOMAXPROCS=%d (<6); measured %.3fx for the record", gomax, parallelScaling)
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Reference implementation: a verbatim copy of the original single-lock
// CircularExemplarStorage append path (types and metrics renamed, and made
// self-contained so it does not depend on anything the submission may have
// refactored). Licensed under Apache 2.0, same as the file it was copied from.
// ─────────────────────────────────────────────────────────────────────────────

const refNoExemplar = -1

type refExemplarStorage struct {
	lock                sync.RWMutex
	exemplars           []refBufferEntry
	nextIndex           int
	metrics             *refMetrics
	oooTimeWindowMillis int64

	index map[string]*refIndexEntry
}

type refIndexEntry struct {
	oldest       int
	newest       int
	seriesLabels labels.Labels
}

type refBufferEntry struct {
	exemplar exemplar.Exemplar
	next     int
	prev     int
	ref      *refIndexEntry
}

type refMetrics struct {
	exemplarsAppended            prometheus.Counter
	exemplarsInStorage           prometheus.Gauge
	seriesWithExemplarsInStorage prometheus.Gauge
	lastExemplarsTs              prometheus.Gauge
	maxExemplars                 prometheus.Gauge
	outOfOrderExemplars          prometheus.Counter
}

func newRefMetrics() *refMetrics {
	return &refMetrics{
		exemplarsAppended:            prometheus.NewCounter(prometheus.CounterOpts{Name: "ref_appended_total"}),
		exemplarsInStorage:           prometheus.NewGauge(prometheus.GaugeOpts{Name: "ref_in_storage"}),
		seriesWithExemplarsInStorage: prometheus.NewGauge(prometheus.GaugeOpts{Name: "ref_series_in_storage"}),
		lastExemplarsTs:              prometheus.NewGauge(prometheus.GaugeOpts{Name: "ref_last_ts"}),
		maxExemplars:                 prometheus.NewGauge(prometheus.GaugeOpts{Name: "ref_max"}),
		outOfOrderExemplars:          prometheus.NewCounter(prometheus.CounterOpts{Name: "ref_ooo_total"}),
	}
}

func newRefExemplarStorage(length int64) *refExemplarStorage {
	c := &refExemplarStorage{
		exemplars: make([]refBufferEntry, length),
		index:     make(map[string]*refIndexEntry, length/16),
		metrics:   newRefMetrics(),
	}
	c.metrics.maxExemplars.Set(float64(length))
	return c
}

func (ce *refExemplarStorage) validateExemplar(idx *refIndexEntry, e exemplar.Exemplar, appended bool) error {
	if len(ce.exemplars) == 0 {
		return storage.ErrExemplarsDisabled
	}

	labelSetLen := 0
	if err := e.Labels.Validate(func(l labels.Label) error {
		labelSetLen += utf8.RuneCountInString(l.Name)
		labelSetLen += utf8.RuneCountInString(l.Value)

		if labelSetLen > exemplar.ExemplarMaxLabelSetLength {
			return storage.ErrExemplarLabelLength
		}
		return nil
	}); err != nil {
		return err
	}

	if idx == nil {
		return nil
	}

	newestExemplar := ce.exemplars[idx.newest].exemplar
	if newestExemplar.Equals(e) {
		return storage.ErrDuplicateExemplar
	}

	if (e.Ts < newestExemplar.Ts && e.Ts <= newestExemplar.Ts-ce.oooTimeWindowMillis) ||
		(e.Ts == newestExemplar.Ts && e.Value < newestExemplar.Value) ||
		(e.Ts == newestExemplar.Ts && e.Value == newestExemplar.Value && e.Labels.Hash() < newestExemplar.Labels.Hash()) {
		if appended {
			ce.metrics.outOfOrderExemplars.Inc()
		}
		return storage.ErrOutOfOrderExemplar
	}
	return nil
}

func (ce *refExemplarStorage) AddExemplar(l labels.Labels, e exemplar.Exemplar) error {
	ce.lock.Lock()
	defer ce.lock.Unlock()

	if len(ce.exemplars) == 0 {
		return storage.ErrExemplarsDisabled
	}

	var buf [1024]byte
	seriesLabels := l.Bytes(buf[:])

	idx, indexExists := ce.index[string(seriesLabels)]
	err := ce.validateExemplar(idx, e, true)
	if err != nil {
		if errors.Is(err, storage.ErrDuplicateExemplar) {
			return nil
		}
		return err
	}

	var insertionIndex int
	var outOfOrder bool
	if indexExists {
		outOfOrder = e.Ts >= ce.exemplars[idx.oldest].exemplar.Ts && e.Ts < ce.exemplars[idx.newest].exemplar.Ts
		if outOfOrder {
			insertionIndex = ce.findInsertionIndex(e, idx)
			if ce.exemplars[insertionIndex].exemplar.Ts == e.Ts {
				return nil
			}
		}
	}

	if !indexExists {
		idx = &refIndexEntry{seriesLabels: l}
		ce.index[string(seriesLabels)] = idx
	}

	if prev := &ce.exemplars[ce.nextIndex]; prev.ref != nil {
		prevRef := prev.ref
		if ce.removeExemplar(prev) {
			if prevRef == idx {
				indexExists = false
			} else {
				ce.removeIndex(prevRef)
			}
		} else if outOfOrder && insertionIndex == ce.nextIndex && prevRef == idx {
			insertionIndex = ce.findInsertionIndex(e, idx)
		}
	}

	ce.exemplars[ce.nextIndex].exemplar = e
	ce.exemplars[ce.nextIndex].ref = idx

	switch {
	case !indexExists:
		idx.oldest = ce.nextIndex
		idx.newest = ce.nextIndex
		ce.exemplars[ce.nextIndex].prev = refNoExemplar
		ce.exemplars[ce.nextIndex].next = refNoExemplar
	case e.Ts >= ce.exemplars[idx.newest].exemplar.Ts:
		ce.exemplars[idx.newest].next = ce.nextIndex
		ce.exemplars[ce.nextIndex].prev = idx.newest
		ce.exemplars[ce.nextIndex].next = refNoExemplar
		idx.newest = ce.nextIndex
	case e.Ts < ce.exemplars[idx.oldest].exemplar.Ts:
		ce.exemplars[idx.oldest].prev = ce.nextIndex
		ce.exemplars[ce.nextIndex].prev = refNoExemplar
		ce.exemplars[ce.nextIndex].next = idx.oldest
		idx.oldest = ce.nextIndex
	default:
		nextExemplar := ce.exemplars[insertionIndex].next
		ce.exemplars[ce.nextIndex].prev = insertionIndex
		ce.exemplars[ce.nextIndex].next = nextExemplar
		ce.exemplars[insertionIndex].next = ce.nextIndex
		if nextExemplar != refNoExemplar {
			ce.exemplars[nextExemplar].prev = ce.nextIndex
		}
	}

	ce.nextIndex = (ce.nextIndex + 1) % len(ce.exemplars)

	ce.metrics.exemplarsAppended.Inc()
	ce.computeMetrics()
	return nil
}

func (ce *refExemplarStorage) removeExemplar(entry *refBufferEntry) bool {
	ref := entry.ref
	if ref == nil {
		return false
	}

	if entry.prev != refNoExemplar {
		ce.exemplars[entry.prev].next = entry.next
	} else {
		ref.oldest = entry.next
	}

	if entry.next != refNoExemplar {
		ce.exemplars[entry.next].prev = entry.prev
	} else {
		ref.newest = entry.prev
	}

	entry.ref = nil

	return ref.oldest == refNoExemplar && ref.newest == refNoExemplar
}

func (ce *refExemplarStorage) removeIndex(ref *refIndexEntry) {
	var buf [1024]byte
	entryLabels := ref.seriesLabels.Bytes(buf[:])
	delete(ce.index, string(entryLabels))
}

func (ce *refExemplarStorage) findInsertionIndex(e exemplar.Exemplar, idx *refIndexEntry) int {
	for i := idx.newest; i != refNoExemplar; {
		current := ce.exemplars[i]
		if current.exemplar.Ts <= e.Ts {
			return i
		}
		i = current.prev
	}
	return idx.oldest
}

func (ce *refExemplarStorage) computeMetrics() {
	ce.metrics.seriesWithExemplarsInStorage.Set(float64(len(ce.index)))

	if len(ce.exemplars) == 0 {
		ce.metrics.exemplarsInStorage.Set(float64(0))
		ce.metrics.lastExemplarsTs.Set(float64(0))
		return
	}

	if ce.exemplars[ce.nextIndex].ref != nil {
		ce.metrics.exemplarsInStorage.Set(float64(len(ce.exemplars)))
		ce.metrics.lastExemplarsTs.Set(float64(ce.exemplars[ce.nextIndex].exemplar.Ts) / 1000)
		return
	}

	ce.metrics.exemplarsInStorage.Set(float64(ce.nextIndex))
	if ce.exemplars[0].ref != nil {
		ce.metrics.lastExemplarsTs.Set(float64(ce.exemplars[0].exemplar.Ts) / 1000)
	}
}
