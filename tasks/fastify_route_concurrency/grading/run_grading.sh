#!/usr/bin/env bash
# Hidden grading for fastify_route_concurrency: one bash function per criterion,
# named exactly as its id in criteria.json. The env runs `run_grading.sh <id>`
# once per row; exit 0 is PASS; a trailing `GRADER_SCORE x` line makes the value
# fractional. Every node run is wrapped in a hard timeout so a hanging
# implementation reads as an explicit failure with the test's own output.

set -u

export PATH="/usr/local/node/bin:/usr/local/bin:/opt/hudvenv/bin:/usr/bin:/bin:${PATH:-}"
export HOME="${HOME:-/root}"

REPO=${REPO_DIR:-/workspace/repo}
G=${GRADER_DIR:-/hud/grader}
export FASTIFY_REPO="$REPO"

# Per-test budget (node --test) and whole-suite budget (timeout). The hidden
# suites finish in well under 20 s on the reference solution.
TEST_TIMEOUT_MS=${TEST_TIMEOUT_MS:-15000}
SUITE_TIMEOUT=${SUITE_TIMEOUT:-120}

# One hidden node:test suite on the public HTTP surface.
run_suite() {
  timeout --signal=KILL "$SUITE_TIMEOUT" \
    node --test --test-timeout="$TEST_TIMEOUT_MS" "$G/tests/$1.test.js"
  local rc=$?
  [ "$rc" -eq 137 ] && echo "suite $1 exceeded ${SUITE_TIMEOUT}s and was killed (hung test)"
  return "$rc"
}

# Every path the agent touched, from the diff headers: "<path>\t<status>".
changed_files() {
  awk '/^diff --git /{ if (p != "") print p "\t" s; p = $4; sub(/^b\//, "", p); s = "modified" }
       /^new file mode/{ s = "added" } /^deleted file mode/{ s = "deleted" }
       END{ if (p != "") print p "\t" s }' "$AGENT_DIFF"
}

# ─── criteria ──────────────────────────────────────────────────────────────

core_concurrency()                 { run_suite core_concurrency; }
fifo_queue_and_overload()          { run_suite fifo_queue_and_overload; }
stream_and_disconnect()            { run_suite stream_and_disconnect; }
plugin_inheritance_and_isolation() { run_suite plugin_inheritance_and_isolation; }
lifecycle_edges()                  { run_suite lifecycle_edges; }

# The hidden type test only uses the public surface the prompt names. It is
# copied next to the repo's own type tests so test/types/tsconfig.json applies,
# run with the repo's own tstyche, then removed.
types_declarations() {
  local target="$REPO/test/types/hud-hidden-concurrency.tst.ts"
  sed 's#FASTIFY_ROOT/#../../#' "$G/types/concurrency.tst.ts" > "$target" || return 1
  (cd "$REPO" && timeout --signal=KILL 300 npx --no-install tstyche test/types/hud-hidden-concurrency.tst.ts)
  local rc=$?
  rm -f "$target"
  return "$rc"
}

# The prompt asks for docs/Reference/ to document the new option and error
# codes; these identifiers are the ones the prompt pins, so checking that the
# documented text mentions them checks what was asked, not a guessed name.
docs_reference() {
  local path status text="" missing=0 tok
  local tokens=(concurrency queueLimit queueTimeout FST_ERR_ROUTE_CONCURRENCY_OPTION_INVALID
                FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL FST_ERR_ROUTE_CONCURRENCY_QUEUE_TIMEOUT)
  while IFS=$'\t' read -r path status; do
    case "$path" in docs/Reference/*) [ "$status" != deleted ] && [ -f "$REPO/$path" ] && text+=$(cat "$REPO/$path")$'\n' ;; esac
  done < <(changed_files)
  [ -z "$text" ] && { echo "  no file under docs/Reference/ changed"; echo "GRADER_SCORE 0"; return 1; }
  for tok in "${tokens[@]}"; do
    grep -qF -- "$tok" <<<"$text" || { echo "  documented, but not mentioning: $tok"; missing=$((missing + 1)); }
  done
  echo "GRADER_SCORE $(awk -v m="$missing" -v n="${#tokens[@]}" 'BEGIN { print (n - m) / n }')"
  [ "$missing" -eq 0 ]
}

# The prompt implies the implementation (lib/ and the package entry points),
# the declarations it names, the docs it names and the tests it asks for.
# 1.0 when every changed path is in scope; -1/3 per stray file. Unweighted:
# reported so a stray file is visible.
scope_discipline() {
  local outside=0 path status
  while IFS=$'\t' read -r path status; do
    case "$path" in lib/*|types/*|test/*|docs/Reference/*|fastify.js|fastify.d.ts) ;;
      *) echo "  outside the allowlist: $path"; outside=$((outside + 1)) ;; esac
  done < <(changed_files)
  echo "GRADER_SCORE $(awk -v n="$outside" 'BEGIN { v = 1 - n / 3; if (v < 0) v = 0; print v }')"
  [ "$outside" -eq 0 ]
}

# The agent's own node:test files under test/ must pass on its tree and fail
# on the baseline (every non-test change reverted). 0.5 when they pass on
# both: they do not exercise the change. A hang counts as a failure: on the
# baseline leg the agent's tests routinely wait forever for a 503 that never
# comes. Mutates the tree; keep it last in criteria.json.
agent_tests() {
  (cd "$REPO" && timeout --signal=KILL 180 node --test --test-timeout=10000 --test-concurrency=1 "$@")
}
test_quality() {
  local files=() path status
  while IFS=$'\t' read -r path status; do
    case "$path" in test/*.test.js|test/*.test.mjs) [ "$status" != deleted ] && files+=("$path") ;; esac
  done < <(changed_files)
  [ ${#files[@]} -eq 0 ] && { echo "  no test file added or changed under test/"; return 1; }
  if ! agent_tests "${files[@]}"; then echo "  the agent's own tests fail (or hang) on the agent's tree"; return 1; fi
  while IFS=$'\t' read -r path status; do
    case "$path" in test/*.test.js|test/*.test.mjs) continue ;; esac
    if [ -f "$G/base/$path" ]; then mkdir -p "$(dirname "$REPO/$path")"; cp -f "$G/base/$path" "$REPO/$path"; else rm -f "$REPO/$path"; fi
  done < <(changed_files)
  if agent_tests "${files[@]}" >/dev/null 2>&1; then
    echo "  tests pass on the baseline too: they do not exercise the change"; echo "GRADER_SCORE 0.5"; return 1
  fi
  echo "  PASS: tests pass on the agent's tree and fail on the baseline"; return 0
}

# ─── gates ─────────────────────────────────────────────────────────────────

# Existing repo tests near the change. All pass on the base commit and on the
# reference solution, so any failure is a regression the submission introduced.
# `test/internals/errors.test.js` is deliberately NOT here: it enumerates every
# error code, so every correct change must edit it. criteria.json lists these
# same files as pristine_paths, so the baseline's own copies are what runs.
regression_existing() {
  (cd "$REPO" && timeout --signal=KILL 600 node --test --test-concurrency=4 --test-timeout=60000 \
    test/route.1.test.js test/route.2.test.js test/route.3.test.js test/route.4.test.js \
    test/route.5.test.js test/route.6.test.js test/route.7.test.js test/route.8.test.js \
    test/route-hooks.test.js test/route-prefix.test.js test/route-shorthand.test.js \
    test/hooks.test.js test/hooks-async.test.js \
    test/handler-timeout.test.js test/handler-context.test.js test/context-config.test.js \
    test/plugin.1.test.js test/plugin.2.test.js test/plugin.3.test.js test/plugin.4.test.js \
    test/register.test.js \
    test/stream.1.test.js test/stream.2.test.js test/stream.3.test.js test/stream.4.test.js test/stream.5.test.js \
    test/request-error.test.js test/request-timeout.test.js test/reply-error.test.js \
    test/set-error-handler.test.js test/encapsulated-error-handler.test.js \
    test/404s.test.js test/500s.test.js test/async-await.test.js test/inject.test.js test/close.test.js \
    test/internals/context.test.js test/internals/handle-request.test.js test/internals/hooks.test.js \
    test/internals/plugin.test.js test/internals/request.test.js test/internals/reply.test.js \
    test/internals/hook-runner.test.js)
}

# Structural anti-tamper gate over the diff: runner and toolchain config the
# prompt never asks anyone to touch must not change; a test file that existed
# at baseline may not be deleted, lose test cases, or gain skips.
anti_hack_gate() {
  local rc=0 path status before after
  local case_re='^[[:space:]]*(test|describe|it)[[:space:]]*\(|^[[:space:]]*expect[[:space:]]*[<(]'
  local skip_re='skip[[:space:]]*:|\.skip[[:space:]]*\(|todo[[:space:]]*:|\.todo[[:space:]]*\('
  while IFS=$'\t' read -r path status; do
    case "$path" in
      package.json|package-lock.json|.borp.yaml|.npmrc|eslint.config.*|tsconfig*.json|test/types/tsconfig.json|.github/*|build/*)
        echo "  protected path changed: $path"; rc=1 ;;
    esac
    case "$path" in test/*.test.js|test/*.test.mjs|test/types/*.tst.ts) ;; *) continue ;; esac
    [ -f "$G/base/$path" ] || continue
    if [ "$status" = deleted ] || [ ! -f "$REPO/$path" ]; then echo "  baseline test file deleted: $path"; rc=1; continue; fi
    before=$(grep -cE "$case_re" "$G/base/$path"); after=$(grep -cE "$case_re" "$REPO/$path")
    [ "$after" -lt "$before" ] && { echo "  test cases removed from $path: $before -> $after"; rc=1; }
    before=$(grep -cE "$skip_re" "$G/base/$path"); after=$(grep -cE "$skip_re" "$REPO/$path")
    [ "$after" -gt "$before" ] && { echo "  skip markers added to $path: $before -> $after"; rc=1; }
  done < <(changed_files)
  return $rc
}

# ─── dispatcher ────────────────────────────────────────────────────────────

CRITERIA="core_concurrency fifo_queue_and_overload stream_and_disconnect plugin_inheritance_and_isolation \
lifecycle_edges types_declarations docs_reference scope_discipline test_quality regression_existing anti_hack_gate"

name="${1:-}"
case " $CRITERIA " in
  *" $name "*)
    if "$name"; then echo "CRITERION $name: PASS"; exit 0; fi
    echo "CRITERION $name: FAIL"; exit 1 ;;
  *)
    echo "usage: run_grading.sh <criterion>; one of: $CRITERIA" >&2; exit 2 ;;
esac
