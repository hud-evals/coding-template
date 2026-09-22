#!/usr/bin/env bash
# Hidden grading for fix_aggregate_listing: one bash function per criterion,
# named exactly as its id in criteria.json. The env runs `run_grading.sh <id>`
# once per row; exit 0 is PASS. Criteria run sequentially (they share the
# runner tree).
#
# Tamper resistance: every Node invocation resolves from the grader-owned
# runner tree ($GRADER_DIR/base, the repo as the agent received it, built),
# never from the agent-writable workspace. Only the agent's SOURCE files
# (packages/*/src, packages/*/test) are synced in; configs, manifests and
# node_modules stay as installed. The untouched src/test/configs are kept in
# $STATE/pristine for the regression and anti-vacuity legs.

set -u

export PATH="/usr/local/bin:/opt/hudvenv/bin:/usr/bin:/bin:${PATH:-}"
export HOME="${HOME:-/root}"

REPO=${REPO_DIR:-/workspace/repo}
G=${GRADER_DIR:-/hud/grader}
RUNNER=$G/base
PKG=$RUNNER/packages/effect-dynamodb
STATE=${GRADER_STATE_DIR:-/hud/logs/grading-state}
LOGDIR=$STATE/logs
PRISTINE=$STATE/pristine
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
  # The untouched sources and configs, before the agent's are synced in.
  mkdir -p "$PRISTINE"
  cp -R "$PKG/src" "$PRISTINE/src"
  cp -R "$PKG/test" "$PRISTINE/test"
  cp "$PKG/vitest.config.ts" "$PKG/vitest.connected.ts" "$PRISTINE/"
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
ordering_equivalence() {
  ensure_setup
  run_hidden __hidden__ordering_equivalence.connected.test.ts
}

# Cursors resume without gaps or duplicates, honour limit, terminate, and
# legacy cursors from deployed clients keep working.
pagination_invariants() {
  ensure_setup
  run_hidden __hidden__pagination_invariants.connected.test.ts
}

# Fan-out must be bounded: measured behaviorally by counting in-flight queries.
# A static scan for `concurrency: "unbounded"` used to run here too, but it
# failed on the string rather than the behavior: a solution that bounds its own
# fan-out around an unbounded combinator is correct and was being rejected.
throughput_discipline() {
  ensure_setup
  run_hidden __hidden__throughput_discipline.test.ts
}

# Page assembly must not issue one query per item (queries counted per page).
n_plus_one() {
  ensure_setup
  run_hidden __hidden__n_plus_one.test.ts
}

# Pre-existing behavior unchanged: hidden regression suite + the two pinned
# cursor tests untouched + the repo's own suites green with pristine configs
# restored over any agent edits. Build failure also fails this criterion.
regression_backcompat() {
  ensure_setup
  local rc=0
  run_hidden __hidden__regression_backcompat.connected.test.ts || rc=1
  python3 "$G/pinned_check.py" \
    "$PRISTINE/test/Aggregate.test.ts" \
    "$REPO/packages/effect-dynamodb/test/Aggregate.test.ts" \
    >"$LOGDIR/pinned.log" 2>&1 || { rc=1; detail "pinned cursor tests" "$LOGDIR/pinned.log"; }
  cp -f "$PRISTINE"/test/*.ts "$PKG/test/"
  cp -f "$PRISTINE/vitest.config.ts" "$PKG/vitest.gunit.ts"
  cp -f "$PRISTINE/vitest.connected.ts" "$PKG/vitest.gconn.ts"
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
test_quality() {
  ensure_setup
  cp -f "$PRISTINE/vitest.config.ts" "$PKG/vitest.gunit.ts"
  cp -f "$PRISTINE/vitest.connected.ts" "$PKG/vitest.gconn.ts"
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
  cp -r "$PRISTINE/src" "$PKG/src"
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

# Repo quality gates: lint and typecheck. Release bookkeeping (changeset or
# version bump) is judged by the llm_rubric row `release_bookkeeping`.
conventions_gates() {
  ensure_setup
  # Drop grader-owned config files so lint sees only the agent's tree.
  rm -f "$PKG/vitest.gunit.ts" "$PKG/vitest.gconn.ts" "$PKG/vitest.hidden.ts"
  local rc=0
  (cd "$RUNNER" && pnpm lint) >"$LOGDIR/lint.log" 2>&1 \
    || { rc=1; echo "  [grader] gate failed: lint"; detail "lint" "$LOGDIR/lint.log"; }
  (cd "$RUNNER" && pnpm --filter effect-dynamodb check \
                && pnpm --filter @effect-dynamodb/schema check) \
    >"$LOGDIR/check.log" 2>&1 \
    || { rc=1; echo "  [grader] gate failed: typecheck"; detail "typecheck" "$LOGDIR/check.log"; }
  return $rc
}

# ─── dispatcher ────────────────────────────────────────────────────────────

CRITERIA="ordering_equivalence pagination_invariants throughput_discipline \
n_plus_one regression_backcompat test_quality conventions_gates"

name="${1:-}"
case " $CRITERIA " in
  *" $name "*)
    if "$name"; then
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
