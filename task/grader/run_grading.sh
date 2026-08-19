#!/usr/bin/env bash
# Hidden grading for fix_aggregate_listing — ONE FUNCTION PER CRITERION.
#
# Usage: run_grading.sh <criterion>
#   criterion ∈ ordering_equivalence | pagination_invariants |
#               throughput_discipline | n_plus_one | regression_backcompat |
#               test_quality | conventions_gates
#
# Exit code is the verdict (0 = PASS). tasks.py runs each criterion as its
# own BashGrader call, so the subscore name in the trace == the function
# name here == the hidden test file it runs. Criteria MUST run sequentially
# (they share the runner tree); tasks.py awaits them one at a time.
#
# Shared setup (sync agent sources into the grader-owned runner + build)
# runs once and is cached in a state dir.
#
# Tamper resistance: every Node invocation resolves from the grader-owned
# runner tree — never from the agent-writable workspace. Only the agent's
# SOURCE files (packages/*/src, packages/*/test) are synced in; configs,
# manifests and node_modules stay pristine.

set -u

export PATH="/usr/local/bin:/opt/hudvenv/bin:/usr/bin:/bin:${PATH:-}"
export HOME="${HOME:-/root}"

REPO=${REPO_DIR:-/workspace/repo}
G=${GRADER_DIR:-/hud/grader}
RUNNER=$G/runner
PKG=$RUNNER/packages/effect-dynamodb
BASE_SHA=$(cat "$G/base_sha")
STATE=${GRADER_STATE_DIR:-/hud/logs/grading-state}
LOGDIR=$STATE/logs
mkdir -p "$LOGDIR"

detail() {
  # detail <label> <logfile> — bounded, indented tail (cannot fake CRITERION lines)
  echo "  ----- $1 (last 2000 bytes) -----"
  tail -c 2000 "$2" 2>/dev/null | sed 's/^/  | /'
  echo "  -----"
}

# ─── shared setup: sync agent sources into the runner + build (cached) ────

sync_agent_sources() {
  local pkg
  for pkgdir in "$RUNNER"/packages/*/; do
    pkg=$(basename "$pkgdir")
    for sub in src test; do
      if [ -d "$REPO/packages/$pkg/$sub" ]; then
        rm -rf "${pkgdir:?}$sub"
        cp -R "$REPO/packages/$pkg/$sub" "$pkgdir$sub"
      fi
    done
  done
  rm -rf "$PKG/src" "$PKG/test"
  cp -R "$REPO/packages/effect-dynamodb/src" "$PKG/src"
  cp -R "$REPO/packages/effect-dynamodb/test" "$PKG/test"
  tar -C "$RUNNER" -cf "$STATE/agent.tar" \
    packages/effect-dynamodb/src \
    packages/effect-dynamodb/test 2>/dev/null
}

restore_agent_state() {
  rm -rf "$PKG/src" "$PKG/test"
  (cd "$RUNNER" && tar -xf "$STATE/agent.tar")
}

ensure_setup() {
  [ -f "$STATE/.setup_done" ] && return 0
  sync_agent_sources
  (cd "$RUNNER" && pnpm --filter @effect-dynamodb/schema build \
                && pnpm --filter effect-dynamodb build) \
    >"$LOGDIR/build.log" 2>&1
  echo $? >"$STATE/build_rc"
  cp "$G/tests/vitest.hidden.ts" "$PKG/vitest.hidden.ts"
  touch "$STATE/.setup_done"
  if [ "$(cat "$STATE/build_rc")" != 0 ]; then
    detail "build" "$LOGDIR/build.log"
  fi
}

# run_hidden <hidden test file> — copy in, run, remove; exit code = verdict
run_hidden() {
  cp "$G/tests/$1" "$PKG/test/$1"
  (cd "$PKG" && npx vitest run --config vitest.hidden.ts "test/$1") \
    >"$LOGDIR/$1.log" 2>&1
  local rc=$?
  rm -f "$PKG/test/$1"
  [ $rc -ne 0 ] && detail "hidden suite" "$LOGDIR/$1.log"
  return $rc
}

# ─── criterion functions: one per grader, named like the subscore ─────────

# Sharded and unsharded listings must return identical feeds (adversarial
# Unicode fixtures; compared against a control implementation).
criterion_ordering_equivalence() {
  ensure_setup
  run_hidden __hidden__ordering_equivalence.connected.test.ts
}

# Cursors resume without gaps or duplicates, honour limit, terminate, and
# legacy cursors from deployed clients keep working.
criterion_pagination_invariants() {
  ensure_setup
  run_hidden __hidden__pagination_invariants.connected.test.ts
}

# Fan-out must be bounded: measured behaviorally by counting in-flight queries.
# A static scan for `concurrency: "unbounded"` used to run here too, but it
# failed on the string rather than the behavior: a solution that bounds its own
# fan-out around an unbounded combinator is correct and was being rejected.
criterion_throughput_discipline() {
  ensure_setup
  run_hidden __hidden__throughput_discipline.test.ts
}

# Page assembly must not issue one query per item (queries counted per page).
criterion_n_plus_one() {
  ensure_setup
  run_hidden __hidden__n_plus_one.test.ts
}

# Pre-existing behavior unchanged: hidden regression suite + the two pinned
# cursor tests untouched + the repo's own suites green with pristine configs
# restored over any agent edits. Build failure also fails this criterion.
criterion_regression_backcompat() {
  ensure_setup
  local rc=0
  run_hidden __hidden__regression_backcompat.connected.test.ts || rc=1
  python3 "$G/pinned_check.py" \
    "$G/pristine/test/Aggregate.test.ts" \
    "$REPO/packages/effect-dynamodb/test/Aggregate.test.ts" \
    >"$LOGDIR/pinned.log" 2>&1 || { rc=1; detail "pinned cursor tests" "$LOGDIR/pinned.log"; }
  cp -f "$G"/pristine/test/*.ts "$PKG/test/"
  cp -f "$G/pristine/vitest.config.ts" "$PKG/vitest.gunit.ts"
  cp -f "$G/pristine/vitest.connected.ts" "$PKG/vitest.gconn.ts"
  (cd "$PKG" && npx vitest run --config vitest.gunit.ts) \
    >"$LOGDIR/pristine-unit.log" 2>&1 || { rc=1; detail "pristine unit suite" "$LOGDIR/pristine-unit.log"; }
  (cd "$PKG" && npx vitest run --config vitest.gconn.ts) \
    >"$LOGDIR/pristine-connected.log" 2>&1 || { rc=1; detail "pristine connected suite" "$LOGDIR/pristine-connected.log"; }
  [ "$(cat "$STATE/build_rc")" != 0 ] && rc=1
  restore_agent_state
  return $rc
}

# The agent's OWN suite must be green as submitted (twice — flake check) and
# must go red when pristine base sources are restored (anti-vacuity).
criterion_test_quality() {
  ensure_setup
  cp -f "$G/pristine/vitest.config.ts" "$PKG/vitest.gunit.ts"
  cp -f "$G/pristine/vitest.connected.ts" "$PKG/vitest.gconn.ts"
  agent_suite() {
    (cd "$PKG" && npx vitest run --config vitest.gunit.ts) \
      && (cd "$PKG" && npx vitest run --config vitest.gconn.ts)
  }
  local rc=0
  agent_suite >"$LOGDIR/agent-suite-1.log" 2>&1 \
    || { rc=1; detail "agent suite run 1" "$LOGDIR/agent-suite-1.log"; }
  if [ $rc -eq 0 ]; then
    agent_suite >"$LOGDIR/agent-suite-2.log" 2>&1 \
      || { rc=1; detail "agent suite run 2 (flake check)" "$LOGDIR/agent-suite-2.log"; }
  fi
  rm -rf "$PKG/src"
  cp -r "$G/pristine/src" "$PKG/src"
  (cd "$RUNNER" && pnpm --filter effect-dynamodb build) >"$LOGDIR/reverted-build.log" 2>&1
  if agent_suite >"$LOGDIR/reverted-suite.log" 2>&1; then
    echo "  [grader] anti-vacuity: agent suite stayed green on pristine base src (vacuous)."
    detail "anti-vacuity run" "$LOGDIR/reverted-suite.log"
    rc=1
  fi
  restore_agent_state
  rm -f "$PKG/vitest.gunit.ts" "$PKG/vitest.gconn.ts"
  # Rebuild against the agent's sources for any criterion that runs after.
  (cd "$RUNNER" && pnpm --filter @effect-dynamodb/schema build \
                && pnpm --filter effect-dynamodb build) \
    >"$LOGDIR/rebuild.log" 2>&1
  return $rc
}

# Repo quality gates: lint, typecheck, and release bookkeeping (a changeset
# entry or a version bump in the agent's diff).
criterion_conventions_gates() {
  ensure_setup
  # Drop grader-owned config files so lint sees only the agent's tree.
  rm -f "$PKG/vitest.gunit.ts" "$PKG/vitest.gconn.ts" "$PKG/vitest.hidden.ts"
  local rc=0
  (cd "$RUNNER" && pnpm lint) >"$LOGDIR/lint.log" 2>&1 \
    || { rc=1; detail "lint" "$LOGDIR/lint.log"; }
  (cd "$RUNNER" && pnpm --filter effect-dynamodb check \
                && pnpm --filter @effect-dynamodb/schema check) \
    >"$LOGDIR/check.log" 2>&1 \
    || { rc=1; detail "typecheck gate" "$LOGDIR/check.log"; }
  local has_changeset=no
  for f in "$REPO"/.changeset/*.md; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in README.md) ;; *) has_changeset=yes ;; esac
  done
  if [ "$has_changeset" = no ]; then
    git -C "$REPO" diff "$BASE_SHA" -- packages/effect-dynamodb/package.json \
      | grep -q '"version"' || rc=1
  fi
  return $rc
}

# ─── dispatcher ────────────────────────────────────────────────────────────

CRITERIA="ordering_equivalence pagination_invariants throughput_discipline \
n_plus_one regression_backcompat test_quality conventions_gates"

name="${1:-}"
case " $CRITERIA " in
  *" $name "*)
    if "criterion_$name"; then
      echo "CRITERION $name: PASS"
      exit 0
    else
      echo "CRITERION $name: FAIL"
      exit 1
    fi
    ;;
  *)
    echo "usage: run_grading.sh <criterion>; one of: $CRITERIA" >&2
    exit 2
    ;;
esac
