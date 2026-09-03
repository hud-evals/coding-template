#!/usr/bin/env bash
# Hidden grading for dump_subset_schema_object_filter - ONE FUNCTION PER CRITERION.
#
# Usage: run_grading.sh <name>
#   scope gates (no weight, no subscore; the env runs gates first):
#             repo_gates_green | full_path_and_api_unchanged |
#             subset_restores_and_rows_exact
#   criteria (one subscore each, five branches x contract/legs):
#             restored_dependency_closure  | legs_dependency_closure  |
#             restored_schema_breadth      | legs_reference_recognition |
#             restored_broken_originals    | legs_broken_originals    |
#             restored_request_shapes      | legs_request_shapes      |
#             next_write_matches_original  | legs_next_write
#   diagnostics kept for the calibration, on no scoreboard:
#             restored_matches_original | behaviour_legs_coverage
#
# the env runs each criterion as its own bash call; the subscore name in
# the trace == the function name here == the hidden check it runs.  Criteria are
# independent and may run in any order; they share a cached build of the dump
# driver, keyed by a content digest of the tree, so a tree that changes is never
# graded from a stale artefact.
#
# Grading is entirely execution-based.  There is no LLM judge anywhere in this
# file, and no check reads the agent's source: everything is decided by running
# the tree's own dump path, loading what it produced with the sqlite3 binary,
# and comparing against expectations frozen outside the container.
#
# Tamper resistance:
#   * the fixture corpus and every expectation live in the grader tree (/hud,
#     0700) and are sha256-checked before use; nothing in /workspace can reach
#     them;
#   * the candidate is exercised through a Go module of the grader's own
#     (gohar), compiled against /workspace/repo by a replace directive written
#     at grading time, so the repo's test helpers are never the oracle;
#   * every Python invocation runs with PYTHONPATH pinned to $GRADER_DIR/lib,
#     so no import resolves into the workspace.
#
# Every criterion but next_write_matches_original is fractional: its check
# prints a GRADER_SCORE line and the env reads the value off it.  The exit
# code is still the plain verdict (0 only when the score is a full 1.0), which
# is what the blocker logic uses.  The gates are read as verdicts only.

set -u

export PATH="/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export HOME="${HOME:-/root}"

REPO=${REPO_DIR:-/workspace/repo}
G=${GRADER_DIR:-/hud/grader}
STATE=${GRADER_STATE_DIR:-/hud/logs/grading-state}
LOGDIR=$STATE/logs
mkdir -p "$LOGDIR"

export REPO_DIR="$REPO"
export GRADER_DIR="$G"
export GRADER_STATE_DIR="$STATE"

PY=${GRADER_PYTHON:-}
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif [ -x /usr/local/bin/python ]; then PY=/usr/local/bin/python
  else PY=python; fi
fi
export PYTHONPATH="$G/lib"
export PYTHONDONTWRITEBYTECODE=1

# Go must never reach for the network while grading; the module cache was
# populated when the image was built.
export GOPROXY=${GRADER_GOPROXY:-off}
export GOTOOLCHAIN=local
export GOCACHE="${GOCACHE:-$STATE/gocache}"
export CGO_ENABLED=1

detail() {
  echo "  ----- $1 (last 2500 bytes) -----"
  tail -c 2500 "$2" 2>/dev/null | sed 's/^/  | /'
  echo "  -----"
}

# run_check <script> [args...] ; echoes the tail of the log on failure and
# re-emits the GRADER_SCORE line so the env can read a fractional criterion
# off stdout.  It forwards its extra arguments to the python check, so the four
# branch checks and the five leg checks share one script each without any of
# them reading the workspace.
run_check() {
  local script=$1; shift
  (cd "$G" && "$PY" "$G/tests/$script" "$@") >"$LOGDIR/$script${1:+.$1}.log" 2>&1
  local rc=$?
  grep -h '^GRADER_SCORE ' "$LOGDIR/$script${1:+.$1}.log" 2>/dev/null | tail -1
  if [ $rc -ne 0 ]; then
    detail "hidden check" "$LOGDIR/$script${1:+.$1}.log"
  fi
  return $rc
}

# ─── criterion functions, v5: one per criterion, named like the subscore ───

# the constraint (no weight, no subscore -- the env runs gates first)
repo_gates_green()            { run_check check_repo_gates_green.py; }
full_path_and_api_unchanged() { run_check check_full_path_and_api_unchanged.py; }
subset_restores_and_rows_exact() { run_check check_subset_restores_and_rows_exact.py; }

# branch 1 -- dependency closure
restored_dependency_closure() { run_check check_restored_class.py dependency_closure; }
legs_dependency_closure()     { run_check check_leg_group.py dependency_closure; }

# branch 2 -- schema breadth
restored_schema_breadth()     { run_check check_restored_class.py schema_breadth; }
legs_reference_recognition()  { run_check check_leg_group.py reference_recognition; }

# branch 3 -- broken originals
restored_broken_originals()   { run_check check_restored_class.py broken_originals; }
legs_broken_originals()       { run_check check_leg_group.py broken_originals; }

# branch 4 -- request shapes
restored_request_shapes()     { run_check check_restored_class.py request_shapes; }
legs_request_shapes()         { run_check check_leg_group.py request_shapes; }

# branch 5 -- what the database does next
next_write_matches_original() { run_check check_next_write_matches_original.py; }
legs_next_write()             { run_check check_leg_group.py next_write; }

# NOTE the old names restored_matches_original and behaviour_legs_coverage are
# gone.  Their scripts stay in tests/ (check_restored_matches_original.py,
# check_behaviour_legs_coverage.py) as the whole-corpus diagnostics the
# calibration prints, but nothing on the scoreboard calls them any more.
restored_matches_original()   { run_check check_restored_matches_original.py; }
behaviour_legs_coverage()     { run_check check_behaviour_legs_coverage.py; }

# Every path the agent touched, from the diff headers: "<path>\t<status>".
changed_files() {
  awk '/^diff --git /{ if (p != "") print p "\t" s; p = $4; sub(/^b\//, "", p); s = "modified" }
       /^new file mode/{ s = "added" } /^deleted file mode/{ s = "deleted" }
       END{ if (p != "") print p "\t" s }' "$AGENT_DIFF"
}

# Structural anti-tamper gate over the diff: the paths no reading of the
# ticket touches (module graph, CI, build and lint config) must not change; a
# Go test file that existed at baseline may not be deleted, lose test
# functions, or gain skips.
anti_hack_gate() {
  local rc=0 path status before after
  while IFS=$'\t' read -r path status; do
    case "$path" in
      go.mod|go.sum|.github/*|.circleci/*|appveyor.yml|Makefile*|.golangci*|.goreleaser*|scripts/*|build/*)
        echo "  protected path changed: $path"; rc=1 ;;
    esac
    case "$path" in *_test.go) ;; *) continue ;; esac
    [ -f "$G/base/$path" ] || continue
    if [ "$status" = deleted ] || [ ! -f "$REPO/$path" ]; then echo "  baseline test file deleted: $path"; rc=1; continue; fi
    before=$(grep -cE '^func Test' "$G/base/$path"); after=$(grep -cE '^func Test' "$REPO/$path")
    [ "$after" -lt "$before" ] && { echo "  test functions removed from $path: $before -> $after"; rc=1; }
    before=$(grep -cE 't\.Skip(f|Now)?\(' "$G/base/$path"); after=$(grep -cE 't\.Skip(f|Now)?\(' "$REPO/$path")
    [ "$after" -gt "$before" ] && { echo "  skip markers added to $path: $before -> $after"; rc=1; }
  done < <(changed_files)
  return $rc
}

# ─── dispatcher ────────────────────────────────────────────────────────────

CRITERIA="repo_gates_green full_path_and_api_unchanged \
subset_restores_and_rows_exact \
restored_dependency_closure legs_dependency_closure \
restored_schema_breadth legs_reference_recognition \
restored_broken_originals legs_broken_originals \
restored_request_shapes legs_request_shapes \
next_write_matches_original legs_next_write \
restored_matches_original behaviour_legs_coverage anti_hack_gate"

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
