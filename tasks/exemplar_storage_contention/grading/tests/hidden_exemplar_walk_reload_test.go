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

// TestExemplarAppendNotBlockedByReloadDuringWalk is the walk-contention
// requirement in the shape it takes in production: the chunk-snapshot writer
// is walking the storage (slowly - it does real work per exemplar) when a
// config reload arrives and resizes the buffer. Appends for other series must
// still not stall.
//
// This is where a storage-wide reader/writer lock on the append path fails
// even though the plain walk test passes: the walk holds the read side for its
// whole duration, the reload queues on the write side, and from that moment
// every new reader - including an append that touches the lock only to
// refresh a gauge every few thousand exemplars - is parked behind the writer
// until the walk is over. Scrapers then stall for as long as the snapshot
// takes. The reference solution keeps the layout lock off the append path
// entirely and does not hold it across the walk's callback; its appends
// measure single-digit milliseconds here.
func TestExemplarAppendNotBlockedByReloadDuringWalk(t *testing.T) {
	const (
		wrCapacity   = 100000
		wrSeries     = 4096
		wrWriters    = 4
		wrSlow       = 300
		wrPerEntry   = 2 * time.Millisecond // ~600ms walk
		wrMaxAppend  = 250 * time.Millisecond
		wrAppendTime = 400 * time.Millisecond
	)

	store, err := NewCircularExemplarStorage(wrCapacity, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	es := store.(*CircularExemplarStorage)

	series := make([]labels.Labels, wrSeries)
	for i := range series {
		series[i] = labels.FromStrings("__name__", "walk_reload", "instance", fmt.Sprintf("i%d", i))
	}
	exLabels := labels.FromStrings("trace_id", "0123456789abcdef")

	// Fill the buffer twice so the walk has a full storage to cover.
	ts := int64(1)
	for k := 0; k < 2*wrCapacity; ts++ {
		for _, l := range series {
			require.NoError(t, es.AddExemplar(l, exemplar.Exemplar{Labels: exLabels, Value: float64(ts), Ts: ts}))
			k++
		}
	}

	// The snapshot writer: a slow walk.
	walkDone := make(chan struct{})
	go func() {
		defer close(walkDone)
		seen := 0
		_ = es.IterateExemplars(func(labels.Labels, exemplar.Exemplar) error {
			if seen < wrSlow {
				time.Sleep(wrPerEntry)
			}
			seen++
			return nil
		})
	}()
	time.Sleep(50 * time.Millisecond)

	// The config reload, arriving while the walk is in progress.
	var resizeTook time.Duration
	resizeDone := make(chan struct{})
	go func() {
		defer close(resizeDone)
		start := time.Now()
		es.Resize(wrCapacity - 1)
		resizeTook = time.Since(start)
	}()
	time.Sleep(20 * time.Millisecond)

	// The scrapers: appends to disjoint series, worst latency recorded.
	var mu sync.Mutex
	var worst time.Duration
	total := 0
	stop := make(chan struct{})
	var wg sync.WaitGroup
	for w := range wrWriters {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			mine := series[w*(wrSeries/wrWriters) : (w+1)*(wrSeries/wrWriters)]
			myTs := ts + int64(w)*(1<<20)
			myWorst := time.Duration(0)
			n := 0
			for {
				select {
				case <-stop:
					mu.Lock()
					if myWorst > worst {
						worst = myWorst
					}
					total += n
					mu.Unlock()
					return
				default:
				}
				for _, l := range mine {
					start := time.Now()
					_ = es.AddExemplar(l, exemplar.Exemplar{Labels: exLabels, Value: float64(myTs), Ts: myTs})
					if d := time.Since(start); d > myWorst {
						myWorst = d
					}
					n++
				}
				myTs++
			}
		}(w)
	}
	time.Sleep(wrAppendTime)
	close(stop)
	wg.Wait()
	<-walkDone
	<-resizeDone

	fmt.Printf("WALKRELOAD worst_append=%s appends=%d resize_took=%s\n", worst, total, resizeTook)
	require.Lessf(t, worst, wrMaxAppend,
		"an AddExemplar blocked for %s while a walk was in progress and a config reload was waiting for it (limit %s): "+
			"ingestion must not stall behind a storage-wide walk, also when a reload arrives during the walk. "+
			"A storage-wide reader/writer lock that the append path takes - even only every few thousand appends - "+
			"parks appends behind the queued reload for the rest of the walk.", worst, wrMaxAppend)
}
