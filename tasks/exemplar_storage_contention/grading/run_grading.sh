#!/usr/bin/env bash
# Hidden grading for the Prometheus exemplar-storage contention task: one bash
# function per criterion, named exactly as its id in criteria.json. The env runs
# `run_grading.sh <id>` once per row; exit 0 is PASS; a trailing
# `GRADER_SCORE x` line makes the value fractional.
#
# The criteria are a matched set, measured on the reference implementations and
# on the seventeen Opus solutions collected so far (HARDENING_REPORT.md §16, §22):
#   * memory_per_stored_exemplar: live heap for the same stored content, ratio
#     against a verbatim copy of the original compiled into the test binary,
#     four content shapes, bound 1.25x (both v19 gold-grade Opus solves FAIL it).
#   * append_not_blocked_by_reload_during_walk: a slow walk, a config reload
#     during it, appends throughout; worst append < 250ms.
#   * append_not_blocked_by_walk: baseline FAILS (659ms); 11 of 15 Opus solutions FAIL.
#   * ingestion_scalability: single-appender floor 0.80; parallel-scaling
#     assertion (1.35x) only on hosts with 6+ CPUs.
#   * concurrent_integrity / snapshot_replay_fidelity / ingestion_order_linearizable
#     MUST run with -race: without it the naive per-series-lock fix passes 13/13.
#   * eviction_is_global: FAILS every design giving fixed partitions a fixed slice.
#   * regression_tsdb (gate): the repo's own exemplar tests still pass.
#   * anti_hack_gate (gate): no baseline test deleted or weakened, no protected
#     path touched. scope_discipline and test_quality are the mechanical axes.
#
# The hidden tests are copied into $REPO/tsdb/ below on every invocation; the
# agent never sees them in its workspace.

set -u

# Grading may run in a shell that does not inherit the image PATH, so
# resolve the toolchain explicitly. Without this every `go` call fails
# with "command not found" and every criterion scores zero.
export PATH="/usr/local/go/bin:/opt/hudvenv/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export HOME="${HOME:-/root}"

REPO=${REPO_DIR:-/workspace/repo}
G=${GRADER_DIR:-/hud/grader}
GRADER_DIR=$G
STATE=${GRADER_STATE_DIR:-/hud/logs/grading-state}
LOGDIR=$STATE/logs
mkdir -p "$LOGDIR"

# Bring the hidden tests in (idempotent; without_hidden_tests moves them out
# again for the legs that must compile the repo's own files only).
for f in "$GRADER_DIR"/tests/hidden_exemplar_*_test.go; do cp -f "$f" "$REPO/tsdb/"; done

HIDDEN_TESTS="$REPO/tsdb/hidden_exemplar_contention_test.go \
$REPO/tsdb/hidden_exemplar_stress_test.go \
$REPO/tsdb/hidden_exemplar_scalability_test.go \
$REPO/tsdb/hidden_exemplar_snapshot_fidelity_test.go \
$REPO/tsdb/hidden_exemplar_eviction_test.go \
$REPO/tsdb/hidden_exemplar_order_linearizability_test.go \
$REPO/tsdb/hidden_exemplar_head_snapshot_test.go \
$REPO/tsdb/hidden_exemplar_alloc_test.go \
$REPO/tsdb/hidden_exemplar_reference_test.go \
$REPO/tsdb/hidden_exemplar_memory_test.go \
$REPO/tsdb/hidden_exemplar_walk_reload_test.go"


# Diagnostics: printed on every run so a failing criterion explains itself
# (uid/PATH/Go-cache permissions are the usual in-container culprits).
echo "  [env] uid=$(id -u) gid=$(id -g) pwd=$(pwd)"
echo "  [env] go=$(command -v go || echo MISSING) $(go version 2>&1 | head -1)"
echo "  [env] GOPATH=${GOPATH:-unset} GOCACHE=${GOCACHE:-unset} GOFLAGS=${GOFLAGS:-unset}"
echo "  [env] repo=$REPO writable=$( [ -w "$REPO" ] && echo yes || echo no )"
echo "  [env] gocache_writable=$( [ -w "${GOCACHE:-/gocache}" ] && echo yes || echo no )"

detail() {
  echo "  ----- $1 (last 3000 bytes) -----"
  tail -c 3000 "$2" 2>/dev/null | sed 's/^/  | /'
  echo "  -----"
}

run_hidden() { # run_hidden <criterion> <-run regex> [extra go test args]
  local name="$1"; local re="$2"; shift 2
  (cd "$REPO" && go test ./tsdb/ -run "$re" -v -count=1 -timeout 900s "$@") \
    >"$LOGDIR/$name.log" 2>&1
  local rc=$?
  [ $rc -ne 0 ] && detail "$name" "$LOGDIR/$name.log"
  return $rc
}

# Ingestion must not stall behind a storage-wide walk. This is the case the
# ticket calls out explicitly ("anything that walks the storage").
append_not_blocked_by_walk() {
  run_hidden append_not_blocked_by_walk 'TestExemplarAppendNotBlockedByIteration'
}

# The ticket's actual objective: parallel appends must scale, and the
# uncontended path must not be taxed for it. Benchmarks the submission
# against a reference copy of the ORIGINAL single-lock implementation that
# is compiled into the hidden test binary itself, so the two run in the
# same process on the same machine and the thresholds are ratios, not
# wall-clock numbers.
ingestion_scalability() {
  # One retry, this criterion only: scheduler noise produces false FAILs on a
  # timing ratio, never false PASSes (non-scaling designs measure <=1.05x and
  # cannot luck past 1.35x). In-container recalibration saw gold flake once in
  # five runs; a retry makes that a ~1-in-600 event while leaving every
  # failing class deterministic.
  run_hidden ingestion_scalability 'TestExemplarIngestionScalability' \
    || run_hidden ingestion_scalability 'TestExemplarIngestionScalability'
}

# No races or corruption under append + resize + query. MUST use -race.
concurrent_integrity() {
  run_hidden concurrent_integrity 'TestExemplarConcurrentAppendResizeIntegrity' -race -count=1
}

# IterateExemplars' global oldest-to-newest contract and the snapshot ->
# replay-into-smaller-buffer round trip, after a sustained -race workload at
# the production default capacity (100k). MUST use -race.
snapshot_replay_fidelity() {
  run_hidden snapshot_replay_fidelity 'TestExemplarSnapshotReplayFidelity' -race -count=1
}

# Eviction is global oldest-first: after sustained 98/2-skewed ingestion the
# storage holds >= 90% of its capacity and at most 10% of it is older than the
# newest max_exemplars ingested. Fails any design that gives fixed partitions
# of series a fixed slice of the buffer.
eviction_is_global() {
  run_hidden eviction_is_global 'TestExemplarEvictionIsGlobal'
}

# IterateExemplars' order is linearizable ingestion order under contended
# appends to the same series with out-of-order rejections, across a resize
# storm; plus the capacity/usable-budget bounds and the replay round trip.
# MUST use -race.
ingestion_order_linearizable() {
  run_hidden ingestion_order_linearizable 'TestExemplarIngestionOrderIsLinearizable' -race -count=1
}

# End to end through the Head: chunk snapshot on shutdown + replay on restart
# at the production default capacity brings the exemplars back in the same
# order (a subsequence: nothing reordered, duplicated or invented), within
# the capacity bound, at least half of them.
head_snapshot_round_trip() {
  run_hidden head_snapshot_round_trip 'TestHeadChunkSnapshotExemplarsRoundTrip'
}

# Zero heap allocations on the steady-state append path, and bounded live
# heap after a resize storm.
append_allocations_memory() {
  run_hidden append_allocations_memory 'TestExemplarAppendAllocationsAndMemory'
}

# Live heap for the same stored content within 1.25x of the original
# implementation (compiled into the test binary), for four content shapes at
# 100k: steady mix, 100k quiet series, 98/2 hot/cold skew, after a reload
# storm. Deterministic (no timing involved).
memory_per_stored_exemplar() {
  run_hidden memory_per_stored_exemplar 'TestExemplarMemoryPerStoredExemplar'
}

# Appends must not stall behind a walk even when a config reload arrives
# while the walk is running (the reload queues on a storage-wide RWMutex and
# parks every later reader, appends included).
append_not_blocked_by_reload_during_walk() {
  run_hidden append_not_blocked_by_reload_during_walk 'TestExemplarAppendNotBlockedByReloadDuringWalk'
}

# Run a command with the hidden tests moved out of the package, then put them
# back, so the command sees the repo's own test files only.
without_hidden_tests() { # without_hidden_tests <logfile> <cmd...>
  local log="$1"; shift
  local moved="" f
  for f in $HIDDEN_TESTS; do
    if [ -f "$f" ]; then mv "$f" "$STATE/$(basename "$f").bak"; moved="$moved $f"; fi
  done
  (cd "$REPO" && "$@") >"$log" 2>&1
  local rc=$?
  for f in $moved; do mv "$STATE/$(basename "$f").bak" "$f"; done
  return $rc
}

# The package must still build, tests included, under the build tag CI uses
# (.github/workflows/ci.yml runs `go test --tags=dedupelabels ./...` and lints
# with that tag). tsdb/head_dedupelabels.go reaches into the exemplar storage's
# internals and only compiles under that tag, so a change that reshapes the
# storage and does not follow through there is a red CI run. `go test -run '^$'`
# compiles the package and its tests (and runs go's default vet subset) without
# executing anything. Deterministic, name free, and passes on the baseline.
ci_build_tags() {
  without_hidden_tests "$LOGDIR/ci_build_tags.log" \
    go test -tags dedupelabels -count=1 -run '^$' -timeout 300s ./tsdb/
  local rc=$?
  [ $rc -ne 0 ] && detail "ci_build_tags" "$LOGDIR/ci_build_tags.log"
  return $rc
}

# Existing behaviour untouched: the repo's own exemplar / resize / chunk
# snapshot tests still pass. Gate (weight 0) in criteria.json. The deleted-test /
# added-skip check lives in the anti-hack gate.
regression_tsdb() {
  without_hidden_tests "$LOGDIR/regression_tsdb.log" \
    go test ./tsdb/ -run 'Exemplar|Resize|ChunkSnapshot' -count=1 -timeout 600s
  local rc=$?
  [ $rc -ne 0 ] && detail "regression_tsdb" "$LOGDIR/regression_tsdb.log"
  return $rc
}

# The agent's own tests, by -run regex, for the test_quality axis. test_quality
# calls this twice: on the agent's tree and again with every non-test change
# reverted. Under -race because the ticket asks for that; the hidden tests are
# out of the package so only the agent's files and the repo's own are compiled.
# A compile failure counts as a failure (on the baseline leg that is the
# expected way for tests of a moved field to "fail").
agent_tests() {
  local re="$1"
  without_hidden_tests "$LOGDIR/agent_tests.log" \
    go test ./tsdb/ -run "$re" -race -count=1 -timeout 600s
  local rc=$?
  cat "$LOGDIR/agent_tests.log"
  return $rc
}


# ─── mechanical axes: read the diff ($AGENT_DIFF) and the pre-change tree ──

# Every path the agent touched, from the diff headers: "<path>\t<status>".
changed_files() {
  awk '/^diff --git /{ if (p != "") print p "\t" s; p = $4; sub(/^b\//, "", p); s = "modified" }
       /^new file mode/{ s = "added" } /^deleted file mode/{ s = "deleted" }
       END{ if (p != "") print p "\t" s }' "$AGENT_DIFF"
}

# The ticket puts the change in the tsdb package and says to leave
# CHANGELOG.md alone: anything under tsdb/ is in scope, new tests included.
# 1.0 when every changed path is in scope; -1/3 per stray file.
scope_discipline() {
  local outside=0 path status
  while IFS=$'\t' read -r path status; do
    case "$path" in tsdb/*) ;; *) echo "  outside the allowlist: $path"; outside=$((outside + 1)) ;; esac
  done < <(changed_files)
  echo "GRADER_SCORE $(awk -v n="$outside" 'BEGIN { v = 1 - n / 3; if (v < 0) v = 0; print v }')"
  [ "$outside" -eq 0 ]
}

# The agent's tests (tsdb/*_test.go it added or changed) must pass on its
# tree and fail on the baseline (every non-test change reverted). 0.5 when
# they pass on both: they do not exercise the change. Mutates the tree; last.
test_quality() {
  local files=() path status names
  while IFS=$'\t' read -r path status; do
    case "$path" in tsdb/*_test.go) [ "$status" != deleted ] && files+=("$path") ;; esac
  done < <(changed_files)
  [ ${#files[@]} -eq 0 ] && { echo "  no test file added or changed under tsdb/"; return 1; }
  names=$(grep -hoE '^func Test[A-Za-z0-9_]+' "${files[@]/#/$REPO/}" | awk '{ print $2 }' | sort -u | paste -sd'|' -)
  [ -z "$names" ] && { echo "  no Test functions in: ${files[*]}"; return 1; }
  if ! agent_tests "^($names)\$"; then echo "  the agent's own tests fail on the agent's tree"; return 1; fi
  while IFS=$'\t' read -r path status; do
    case "$path" in *_test.go) continue ;; esac
    if [ -f "$G/base/$path" ]; then mkdir -p "$(dirname "$REPO/$path")"; cp -f "$G/base/$path" "$REPO/$path"; else rm -f "$REPO/$path"; fi
  done < <(changed_files)
  if agent_tests "^($names)\$" >/dev/null; then
    echo "  tests pass on the baseline too: they do not exercise the change"; echo "GRADER_SCORE 0.5"; return 1
  fi
  echo "  PASS: tests pass on the agent's tree and fail on the baseline"; return 0
}

# Structural anti-tamper gate over the diff: the protected paths (CI,
# toolchain, module graph, lint and build config, the hidden tests) must not
# change; a Go test file that existed at baseline may not be deleted, lose
# test functions, or gain skips.
anti_hack_gate() {
  local rc=0 path status before after
  while IFS=$'\t' read -r path status; do
    case "$path" in
      go.mod|go.sum|go.work|go.work.sum|.github/*|.golangci.yml|.promu.yml|.yamllint|Makefile|Makefile.common|scripts/*|tsdb/hidden_exemplar_*_test.go)
        echo "  protected path changed: $path"; rc=1 ;;
    esac
    case "$path" in *_test.go) ;; *) continue ;; esac
    [ -f "$G/base/$path" ] || continue
    if [ "$status" = deleted ] || [ ! -f "$REPO/$path" ]; then echo "  baseline test file deleted: $path"; rc=1; continue; fi
    before=$(grep -cE '^func Test[A-Za-z0-9_]*\(' "$G/base/$path"); after=$(grep -cE '^func Test[A-Za-z0-9_]*\(' "$REPO/$path")
    [ "$after" -lt "$before" ] && { echo "  test functions removed from $path: $before -> $after"; rc=1; }
    before=$(grep -cE 't\.Skip(f|Now)?\(' "$G/base/$path"); after=$(grep -cE 't\.Skip(f|Now)?\(' "$REPO/$path")
    [ "$after" -gt "$before" ] && { echo "  skip markers added to $path: $before -> $after"; rc=1; }
  done < <(changed_files)
  return $rc
}

# ─── dispatcher ────────────────────────────────────────────────────────────

CRITERIA="append_not_blocked_by_walk ingestion_scalability concurrent_integrity snapshot_replay_fidelity \
eviction_is_global ingestion_order_linearizable head_snapshot_round_trip append_allocations_memory \
memory_per_stored_exemplar append_not_blocked_by_reload_during_walk ci_build_tags scope_discipline test_quality \
regression_tsdb anti_hack_gate"

name="${1:-}"
case " $CRITERIA " in
  *" $name "*)
    if "$name"; then
      echo "CRITERION $name: PASS"; exit 0
    else
      echo "CRITERION $name: FAIL"; exit 1
    fi
    ;;
  *)
    echo "usage: run_grading.sh <criterion>; one of: $CRITERIA" >&2; exit 2 ;;
esac
