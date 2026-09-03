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

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
)

// TestExemplarConcurrentAppendResizeIntegrity hammers the storage the way a
// busy Prometheus does: many scrapers appending for disjoint series while a
// config reload resizes the buffer underneath them and queries run alongside.
//
// The invariants are the ones a user actually depends on:
//   - never panic, never corrupt the index, never race
//   - a series' exemplars come back in the order they were ingested
//   - the configured capacity is a real upper bound on what is retained
//
// This only bites once the buffer has wrapped and a resize interleaves with
// appends, which is why it runs a lot of operations rather than a handful.
// Run it with -race and a high -count.
func TestExemplarConcurrentAppendResizeIntegrity(t *testing.T) {
	const (
		capacity        = 65536
		writers         = 8
		seriesPerWriter = 64
		appendsPerLoop  = 400
	)

	store, err := NewCircularExemplarStorage(capacity, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	es := store.(*CircularExemplarStorage)

	seriesFor := func(w, s int) labels.Labels {
		return labels.FromStrings("__name__", "stress", "w", fmt.Sprintf("%d", w), "s", fmt.Sprintf("%d", s))
	}

	var wgWriters, wgBackground sync.WaitGroup
	stop := make(chan struct{})

	// Writers: each owns its series, so timestamps for any given series are
	// strictly increasing by construction.
	for w := range writers {
		wgWriters.Add(1)
		go func() {
			defer wgWriters.Done()
			ts := int64(1)
			for range appendsPerLoop {
				for s := range seriesPerWriter {
					// Errors are expected while the storage is disabled or the
					// value is rejected as out of order; corruption is not.
					_ = es.AddExemplar(seriesFor(w, s), exemplar.Exemplar{
						Labels: labels.FromStrings("trace_id", fmt.Sprintf("%d-%d-%d", w, s, ts)),
						Value:  float64(ts),
						Ts:     ts,
					})
				}
				ts++
			}
		}()
	}

	// Resizer: crosses any plausible "is it worth sharding" threshold in both
	// directions, and passes through the disabled state.
	wgBackground.Add(1)
	go func() {
		defer wgBackground.Done()
		sizes := []int64{capacity, 16384, 16383, 1000, 0, 100, 16384, 32768, capacity}
		for {
			for _, n := range sizes {
				select {
				case <-stop:
					return
				default:
				}
				es.Resize(n)
			}
		}
	}()

	// Reader: queries and full walks concurrently with all of the above.
	wgBackground.Add(1)
	go func() {
		defer wgBackground.Done()
		m := []*labels.Matcher{labels.MustNewMatcher(labels.MatchEqual, "__name__", "stress")}
		for {
			select {
			case <-stop:
				return
			default:
			}
			_, _ = es.Select(0, 1<<62, m)
			_ = es.IterateExemplars(func(labels.Labels, exemplar.Exemplar) error { return nil })
		}
	}()

	// Writers are bounded; once they are done, stop the background goroutines.
	wgWriters.Wait()
	close(stop)
	wgBackground.Wait()

	// Settle on a known capacity and verify the invariants.
	es.Resize(capacity)

	total := 0
	for w := range writers {
		for s := range seriesPerWriter {
			l := seriesFor(w, s)
			m := []*labels.Matcher{
				labels.MustNewMatcher(labels.MatchEqual, "__name__", "stress"),
				labels.MustNewMatcher(labels.MatchEqual, "w", fmt.Sprintf("%d", w)),
				labels.MustNewMatcher(labels.MatchEqual, "s", fmt.Sprintf("%d", s)),
			}
			res, err := es.Select(0, 1<<62, m)
			require.NoError(t, err)
			for _, qr := range res {
				require.Equal(t, l.String(), qr.SeriesLabels.String())
				for i := 1; i < len(qr.Exemplars); i++ {
					require.LessOrEqualf(t, qr.Exemplars[i-1].Ts, qr.Exemplars[i].Ts,
						"series %s returned exemplars out of ingestion order: %d after %d",
						l.String(), qr.Exemplars[i].Ts, qr.Exemplars[i-1].Ts)
				}
				total += len(qr.Exemplars)
			}
		}
	}

	require.LessOrEqualf(t, total, capacity,
		"retained %d exemplars with a configured capacity of %d: the capacity bound was not honoured",
		total, capacity)
}
