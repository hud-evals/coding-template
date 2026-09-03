"""The repo's own gates, run over a tree and reduced to a comparable shape.

The last line of the ticket: "The repo's own gates apply: gofmt -l . clean,
go vet ./..., and go test green on the packages you touch."

Nothing here judges style or coverage. It runs what the repo runs and reports
what came out, so the grader can subtract what the untouched checkout already
produced. That subtraction is not politeness: the pinned toolchain in the image
is Go 1.26, and on a newer one the db package fails Test_Geopoly on a pristine
HEAD -- a phantom failure that has nothing to do with the change under test.
An agent is never charged for a failure the base tree already had.

Two things beyond that subtraction, and both exist for one reason: an answer we
did not get is not a verdict against the tree.

  * ONE SAMPLE OF THIS SUITE IS NOT A MEASUREMENT.  The packages the gate runs
    are wall-clock bound in places -- ./store/ brings a real Raft node up and
    waits ten seconds for an election, db/checkpoint_manager_test.go sleeps two
    seconds and then asserts a checkpoint happened, ./http/ opens real
    listeners -- and the tests an agent adds inherit those helpers.  On a
    machine that is busy, any of them can lose a race it wins every other time.
    So a test that is red here and green in the baseline is re-run ON ITS OWN,
    up to CONFIRMATIONS times, and only a test that loses every one of those
    isolated runs is reported as a failure.  What is measured does not change:
    the question is still "does this test fail on this tree", asked until the
    answer stops depending on what else the machine was doing.

  * A STEP THAT NEVER FINISHED REPORTS "unmeasured", NOT "failed".  A timeout,
    a toolchain that will not start, or the criterion's own time budget running
    out used to surface as a non-zero exit and be scored exactly like a broken
    tree.  Those now come back in "unmeasured" and the check declines to charge
    them.  BUDGET_SECONDS keeps the whole criterion inside the timeout tasks.py
    gives it, so the answer is ours to interpret rather than a killed process.
"""

import json
import os
import subprocess
import time

# The packages the change is allowed to reach, plus the three subset-backup
# tests that already live in the store package (store_test.go:1690/1732/1800).
# The whole store suite is long and timing-sensitive, so it is not run.
TEST_PACKAGES = ["./db/...", "./http/...", "./command/...", "./cmd/..."]
STORE_RUN = "Test_SingleNodeBackup"

# How many isolated re-runs a newly red test has to lose before it is charged.
# One clean isolated run is enough to leave it uncharged: at that point the
# suite and the test disagree, and a disagreement is not evidence against the
# tree.
CONFIRMATIONS = 3

# Above this many newly red tests, nothing is re-run: a busy machine loses a
# race here and there, it does not turn a dozen green tests red at once, and
# re-running a wholesale breakage one test at a time only risks talking the
# criterion out of a verdict it already has.
TOO_MANY = 12

# The criterion's own budget.  tasks.py allows repo_gates_green 3600 seconds;
# everything here -- gates, re-runs and all -- has to land inside this, so the
# check gets to say "not measured" instead of being killed mid-sentence.  It is
# a constant on purpose: an environment knob for it would be a free pass out of
# the criterion for anything that can reach the grading process's environment.
BUDGET_SECONDS = 3000.0

_deadline = None
_budget = BUDGET_SECONDS


class Unmeasured(RuntimeError):
    """A step did not produce an answer: it timed out, the toolchain would not
    run, or the budget ran out.  Not a verdict about the tree."""


def _env():
    env = dict(os.environ)
    env.update({"GOWORK": "off", "GOFLAGS": "", "GOTOOLCHAIN": "local",
                "CGO_ENABLED": "1"})
    env.setdefault("GOPROXY", env.get("GRADER_GOPROXY", "off"))
    env.setdefault("HOME", "/root")
    return env


def _allowed(timeout):
    """The wall clock this step may have: its own limit, or whatever is left of
    the criterion's budget, whichever is smaller."""
    if _deadline is None:
        return timeout
    left = _deadline - time.monotonic()
    if left <= 5:
        raise Unmeasured("the criterion's %ds budget ran out" % int(_budget))
    return min(timeout, left)


def _run(args, repo, timeout):
    limit = _allowed(timeout)
    try:
        return subprocess.run(args, cwd=repo, env=_env(), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=limit)
    except subprocess.TimeoutExpired:
        raise Unmeasured("`%s` did not finish within %ds"
                         % (" ".join(args), int(limit)))
    except OSError as exc:
        raise Unmeasured("`%s` could not be run: %s" % (" ".join(args), exc))


def _out(args, repo, timeout):
    return _run(args, repo, timeout).stdout.decode("utf-8", "replace")


def gofmt(repo):
    p = _run(["gofmt", "-l", "."], repo, 600)
    return sorted(x.strip() for x in p.stdout.decode("utf-8", "replace").splitlines()
                  if x.strip())


def vet(repo):
    p = _run(["go", "vet", "./..."], repo, 1200)
    if p.returncode == 0:
        return []
    return [x for x in p.stdout.decode("utf-8", "replace").splitlines() if x.strip()][-40:]


def build(repo):
    p = _run(["go", "build", "./..."], repo, 1200)
    if p.returncode == 0:
        return []
    return [x for x in p.stdout.decode("utf-8", "replace").splitlines() if x.strip()][-40:]


def _tests_from_json(raw):
    """{package::test} for every failure, plus {package::<package>} when a
    package fell over without naming a test (a build error, or a panic)."""
    failures = set()
    pkg_fail = set()
    pkg_test_fail = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("Action") != "fail":
            continue
        pkg = ev.get("Package", "?")
        test = ev.get("Test")
        if test:
            if "/" in test:  # subtests follow their parent
                continue
            failures.add("%s::%s" % (pkg, test))
            pkg_test_fail.add(pkg)
        else:
            pkg_fail.add(pkg)
    for pkg in sorted(pkg_fail - pkg_test_fail):
        failures.add("%s::<package did not run>" % pkg)
    return sorted(failures)


def tests(repo):
    """One pass of the suite.  What comes back here is a first sample, not a
    verdict; confirm() decides what a new failure means."""
    out = []
    out.append(_out(["go", "test", "-json", "-count=1"] + TEST_PACKAGES, repo, 2400))
    out.append(_out(["go", "test", "-json", "-count=1", "-run", STORE_RUN, "./store/"],
                    repo, 1200))
    return _tests_from_json("\n".join(out))


def _reproduced(raw, pkg, test):
    got = set(_tests_from_json(raw))
    if ("%s::<package did not run>" % pkg) in got:
        return True
    if test.startswith("<"):
        return any(g.startswith(pkg + "::") for g in got)
    return ("%s::%s" % (pkg, test)) in got


def confirm(repo, entries, attempts=CONFIRMATIONS):
    """Re-run each entry on its own and see whether it is still red.

    Returns (confirmed, unconfirmed, notes).  A test the isolated runs cannot
    make fail again is left in `unconfirmed` and charged to nobody: the suite
    and the test disagreed, and that disagreement is about the machine, not
    about the tree.

    An entry whose re-run itself could not be completed stays CONFIRMED, and
    that is the one place this file does not shrug something off.  The suite
    already measured it red once; a re-run that hangs for its whole 900 seconds
    is a test that hangs, and a budget that ran out is not a reason to hand a
    red tree a green criterion.  "Not measured is not a failure" is about
    answers we never had, not about second opinions we could not afford.
    """
    confirmed, unconfirmed, notes = [], [], []
    for entry in entries:
        pkg, _, test = entry.partition("::")
        if test.startswith("<"):
            args = ["go", "test", "-json", "-count=1", pkg]
        else:
            args = ["go", "test", "-json", "-count=1", "-run", "^%s$" % test, pkg]
        losses = ran = 0
        try:
            for _attempt in range(attempts):
                raw = _out(args, repo, 900)
                ran += 1
                if not _reproduced(raw, pkg, test):
                    break
                losses += 1
        except Unmeasured as exc:
            confirmed.append(entry)
            notes.append((entry, "kept as a failure: %s" % exc))
            continue
        if ran and losses == ran:
            confirmed.append(entry)
        else:
            unconfirmed.append(entry)
    return sorted(confirmed), sorted(unconfirmed), notes


STEPS = (("build", build), ("gofmt", gofmt), ("vet", vet), ("tests", tests))


def _charges(step, now, baseline):
    """Would this step's output, as it stands, cost the run the criterion?

    The same three comparisons check_repo_gates_green.py makes, in one place,
    so a gate can be asked to repeat itself when -- and only when -- its answer
    is about to be charged to somebody.
    """
    if step == "build":
        return bool(now)
    if step == "gofmt":
        return bool(set(now) - set(baseline["gofmt"]))
    if step == "vet":
        return bool(now) and not baseline["vet"]
    return False


def collect(repo, baseline=None, budget=None):
    """Run every gate over `repo`.

    With a `baseline` (the pristine checkout's own record), nothing is charged
    on a single sample.  A test failure the baseline does not have is re-run on
    its own (see confirm()); a build, gofmt or vet problem the baseline does not
    have is re-run whole.  Either way the finding has to survive CONFIRMATIONS
    attempts to count -- a compiler that could not fork, a vet subprocess that
    lost a file descriptor, a test that lost a race on a busy machine, all say
    something about the machine and nothing about the tree.

    Without a baseline nothing is confirmed away: that is how the baseline
    itself is recorded, where a failure seen even once belongs in the record,
    because everything in the record is subtracted from every run later.

    A tree with more than TOO_MANY new failures is not re-run at all.  A busy
    machine loses a race here and there; it does not turn a dozen green tests
    red at once, and confirming a wholesale breakage one test at a time is how
    a criterion talks itself out of a verdict it already has.

    Returns the four gate results plus three bookkeeping fields:
      unmeasured  {step: why} for anything that never produced an answer;
      unconfirmed [names] that were red once and green when asked again;
      notes       {what: why} for findings kept without a second opinion.
    """
    global _deadline, _budget
    _budget = BUDGET_SECONDS if budget is None else budget
    _deadline = time.monotonic() + _budget
    try:
        result = {"build": [], "gofmt": [], "vet": [], "tests": [],
                  "unmeasured": {}, "unconfirmed": [], "notes": {}}
        for step, fn in STEPS:
            try:
                result[step] = fn(repo)
            except Unmeasured as exc:
                result["unmeasured"][step] = str(exc)

        if baseline is None:
            return result

        for step, fn in STEPS:
            if step == "tests" or step in result["unmeasured"]:
                continue
            if not _charges(step, result[step], baseline):
                continue
            for _attempt in range(CONFIRMATIONS - 1):
                try:
                    again = fn(repo)
                except Unmeasured as exc:
                    # The first answer stands: it was measured, and a second
                    # opinion we could not afford is not a reason to drop it.
                    result["notes"]["re-run of " + step] = \
                        "kept as a failure: %s" % exc
                    break
                result[step] = again
                if not _charges(step, again, baseline):
                    result["unconfirmed"].append(
                        "%s (reported a problem once, none when it was run again)" % step)
                    break

        if "tests" not in result["unmeasured"]:
            new = sorted(set(result["tests"]) - set(baseline.get("tests", [])))
            if len(new) > TOO_MANY:
                result["notes"]["tests"] = (
                    "%d new failures: too many to be a machine losing a race, "
                    "charged as measured" % len(new))
            elif new:
                _confirmed, unconfirmed, notes = confirm(repo, new)
                for entry, why in notes:
                    result["notes"]["re-run of " + entry] = why
                result["tests"] = sorted(set(result["tests"]) - set(unconfirmed))
                result["unconfirmed"] += sorted(unconfirmed)
        return result
    finally:
        _deadline = None
