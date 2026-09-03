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

	"github.com/stretchr/testify/require"

	"github.com/prometheus/prometheus/model/exemplar"
	"github.com/prometheus/prometheus/model/labels"
)

// TestExemplarEvictionIsGlobal pins the retention policy of the storage: when
// the buffer is full, the exemplar that makes room is (approximately) the
// OLDEST one in the whole storage, whichever series it belongs to, so that
// after sustained ingestion the storage holds approximately the most recent
// max_exemplars exemplars that were ingested. That is what a circular buffer
// promises, what prometheus_tsdb_exemplar_last_exemplars_timestamp_seconds
// reports, and what a fleet with a few very hot services and thousands of
// quiet ones depends on: a design that gives every fixed partition of series
// its own fixed slice of the buffer lets a partition holding a hot service
// evict exemplars from a minute ago while the partitions holding only quiet
// services sit mostly empty or keep exemplars from an hour ago - and then the
// configured budget is neither respected in spirit nor even used.
//
// The workload is deliberately extreme - 8 hot series produce 98% of the
// exemplars, 8192 cold series the remaining 2% - and appended from a single
// goroutine with a globally increasing timestamp, so ingestion order is known
// exactly and "the newest max_exemplars exemplars" is a precise set. The
// tolerance (10%) is generous: it leaves room for a design that balances
// capacity by measured ingestion rate rather than tracking exact global
// order, but not for one that partitions capacity statically.
func TestExemplarEvictionIsGlobal(t *testing.T) {
	const (
		evCapacity = 100000
		evHot      = 8
		evCold     = 8192
		evColdOneIn = 50 // 2% of appends go to cold series
		evAppends  = 10 * evCapacity
		evSlack    = evCapacity / 10
	)

	store, err := NewCircularExemplarStorage(evCapacity, NewExemplarMetrics(nil), 0)
	require.NoError(t, err)
	es := store.(*CircularExemplarStorage)

	hot := make([]labels.Labels, evHot)
	for s := range hot {
		hot[s] = labels.FromStrings("__name__", "hot", "s", fmt.Sprintf("%d", s))
	}
	cold := make([]labels.Labels, evCold)
	for s := range cold {
		cold[s] = labels.FromStrings("__name__", "cold", "s", fmt.Sprintf("%d", s))
	}
	exLabels := labels.FromStrings("trace_id", "eviction")

	for k := range evAppends {
		l := hot[k%evHot]
		if k%evColdOneIn == 0 {
			l = cold[(k/evColdOneIn)%evCold]
		}
		require.NoError(t, es.AddExemplar(l, exemplar.Exemplar{Labels: exLabels, Value: float64(k), Ts: int64(k)}))
	}

	// Everything with ts < cutoff was ingested more than max_exemplars appends
	// ago and should be gone; everything at or after it should still be there.
	const cutoff = int64(evAppends - evCapacity)
	var total, stale, prevTs int64
	oldestTs := int64(-1)
	staleExample := ""
	require.NoError(t, es.IterateExemplars(func(l labels.Labels, e exemplar.Exemplar) error {
		total++
		if oldestTs == -1 {
			oldestTs = e.Ts
		}
		require.GreaterOrEqualf(t, e.Ts, prevTs, "IterateExemplars yielded ts %d after ts %d: not global ingestion order", e.Ts, prevTs)
		prevTs = e.Ts
		if e.Ts < cutoff {
			stale++
			if staleExample == "" {
				staleExample = fmt.Sprintf("series %s, ts %d (ingested %d appends before the cutoff)", l.String(), e.Ts, cutoff-e.Ts)
			}
		}
		return nil
	}))
	fmt.Printf("EVICT retained=%d stale=%d oldest_ts=%d cutoff=%d\n", total, stale, oldestTs, cutoff)

	require.LessOrEqualf(t, total, int64(evCapacity), "retained %d exemplars with max_exemplars %d", total, evCapacity)
	require.GreaterOrEqualf(t, total, int64(evCapacity-evSlack),
		"the storage retains only %d of a budgeted %d exemplars after %d appends: the budget must be usable under a skewed series distribution too "+
			"(a partition that receives 2%% of the exemplars but owns 90%% of the capacity leaves the budget unused)",
		total, evCapacity, evAppends)
	require.LessOrEqualf(t, stale, int64(evSlack),
		"%d retained exemplars (%.0f%%) are older than the newest %d ingested (for example %s), i.e. they survived while newer "+
			"exemplars were evicted to make room. Eviction must be (approximately) global oldest-first across the whole storage, "+
			"not per fixed partition.",
		stale, 100*float64(stale)/float64(evCapacity), evCapacity, staleExample)
}
