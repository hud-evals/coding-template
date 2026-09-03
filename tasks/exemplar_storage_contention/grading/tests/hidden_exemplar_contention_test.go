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
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
)

// exemplarContentionCapacity is above whatever threshold an implementation
// may use to decide sharding is worthwhile, and matches the order of
// magnitude of Prometheus's own default (max_exemplars: 100000).
const exemplarContentionCapacity = 100000

func hiddenFillExemplars(t testing.TB, es *CircularExemplarStorage, series, perSeries int) {
	t.Helper()
	ts := int64(1)
	for i := range series {
		l := labels.FromStrings("__name__", "metric", "series", fmt.Sprintf("%d", i))
		for range perSeries {
			require.NoError(t, es.AddExemplar(l, exemplar.Exemplar{
				Labels: labels.FromStrings("trace_id", fmt.Sprintf("t%d", ts)),
				Value:  float64(ts),
				Ts:     ts,
			}))
			ts++
		}
	}
}

// TestExemplarAppendNotBlockedByIteration asserts that ingesting an exemplar
// for one series is not held up while another caller walks the storage.
//
// IterateExemplars is used by the chunk-snapshot writer, which does real work
// per exemplar. If the storage holds one lock across the whole walk -- and
// invokes the callback while holding it -- then every scraper in the process
// stalls for as long as that walk takes. This test makes the walk slow on
// purpose so the stall is unambiguous rather than a timing coincidence.
//
// The threshold is loose: an implementation that isolates series from each
// other, or that simply does not run the callback under a lock, lands orders
// of magnitude below it.
func TestExemplarAppendNotBlockedByIteration(t *testing.T) {
	const (
		series       = 500
		perSeries    = 4
		slowEntries  = 300
		perEntry     = 2 * time.Millisecond // => ~600ms of lock hold if held throughout
		maxAppendDur = 250 * time.Millisecond
	)

	store, err := NewCircularExemplarStorage(exemplarContentionCapacity, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	es := store.(*CircularExemplarStorage)

	hiddenFillExemplars(t, es, series, perSeries)

	iterDone := make(chan struct{})
	go func() {
		defer close(iterDone)
		seen := 0
		_ = es.IterateExemplars(func(_ labels.Labels, _ exemplar.Exemplar) error {
			if seen < slowEntries {
				time.Sleep(perEntry)
			}
			seen++
			return nil
		})
	}()

	// Let the walk get going.
	time.Sleep(100 * time.Millisecond)

	appendLabels := labels.FromStrings("__name__", "metric", "series", "0")
	var worst time.Duration
	for i := range 10 {
		start := time.Now()
		err := es.AddExemplar(appendLabels, exemplar.Exemplar{
			Labels: labels.FromStrings("trace_id", fmt.Sprintf("late%d", i)),
			Value:  1,
			Ts:     int64(series*perSeries) + int64(i) + 1,
		})
		d := time.Since(start)
		require.NoError(t, err)
		if d > worst {
			worst = d
		}
		time.Sleep(5 * time.Millisecond)
	}

	require.Lessf(t, worst, maxAppendDur,
		"an AddExemplar blocked for %s while another goroutine was iterating the storage (limit %s): "+
			"ingestion is serialized behind a storage-wide walk", worst, maxAppendDur)

	<-iterDone
}
