"""Criterion 1 -- the repo's own gates. Gate: green on the untouched tree.

Last line of the ticket: "Add tests in the repo's style for the behaviour you
change. The repo's own gates apply: gofmt -l . clean, go vet ./..., and go test
green on the packages you touch."

Everything is measured against the baseline recorded from the pristine checkout
inside this image, so a failure the base tree already had -- Test_Geopoly is one
on a toolchain newer than the pinned Go 1.26 -- is never charged to a run. Only
what the change broke counts.

A broken baseline is an infrastructure problem, not a verdict: if the untouched
tree does not build, the criterion says so and stops.

Two more things are infrastructure rather than verdicts, and lib/gates.py hands
them over separately so this file can say so out loud:

  * a finding that did not survive being asked again.  A test that went red in
    the suite and green on three isolated re-runs of its own; a build, vet or
    gofmt problem that was there once and gone when the gate was run again.
    This suite waits on wall-clock in several places (a Raft election in
    ./store/, two-second checkpoint sleeps in ./db/, real listeners in ./http/),
    the tests an agent adds inherit those helpers, and go build and go vet fan
    out into subprocesses of their own, so one red sample on a busy machine is
    not evidence that the change broke anything.  It is reported and not
    charged;

  * a gate that never finished -- a timeout, or the criterion's time budget
    running out.  An answer we do not have is not a failure of the tree.

Neither widens what the criterion means. Both stop it from charging a run for
something it did not actually measure.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import checkbase as cb  # noqa: E402
import gates  # noqa: E402

BASELINE = os.path.join(cb.GRADER_DIR, "data", "gates_baseline.json")
REPO = os.environ.get("REPO_DIR", "/workspace/repo")

r = cb.Report("criterion 1: the repo's own gates, minus what the base already failed")

if not os.path.exists(BASELINE):
    print("  INFRA_FAIL: no gates baseline was recorded when the image was built")
    sys.exit(1)
with open(BASELINE) as fh:
    base = json.load(fh)

now = gates.collect(REPO, baseline=base)
unmeasured = now["unmeasured"]

if "build" in unmeasured:
    r.ok("go build ./... was not measured (%s); not charged", unmeasured["build"])
elif now["build"]:
    r.fail("go build ./... fails:\n    %s", "\n    ".join(now["build"][-20:]))
else:
    r.ok("go build ./...")

if "gofmt" in unmeasured:
    r.ok("gofmt -l . was not measured (%s); not charged", unmeasured["gofmt"])
else:
    new_fmt = sorted(set(now["gofmt"]) - set(base["gofmt"]))
    if new_fmt:
        r.fail("gofmt -l . reports %d file(s) this change left unformatted: %s",
               len(new_fmt), new_fmt[:10])
    else:
        r.ok("gofmt -l . clean (baseline: %d pre-existing)", len(base["gofmt"]))

if "vet" in unmeasured:
    r.ok("go vet ./... was not measured (%s); not charged", unmeasured["vet"])
elif now["vet"] and not base["vet"]:
    r.fail("go vet ./... now reports:\n    %s", "\n    ".join(now["vet"][-20:]))
elif now["vet"]:
    r.ok("go vet ./... reports only what the base tree reported")
else:
    r.ok("go vet ./...")

if "tests" in unmeasured:
    r.ok("go test was not measured (%s); not charged", unmeasured["tests"])
else:
    new_tests = sorted(set(now["tests"]) - set(base["tests"]))
    fixed = sorted(set(base["tests"]) - set(now["tests"]))
    if new_tests and len(new_tests) > gates.TOO_MANY:
        r.fail("go test: %d test(s) fail that the base tree passed -- too many for "
               "a machine losing a race, so they stand as measured:\n    %s",
               len(new_tests), "\n    ".join(new_tests[:20]))
    elif new_tests:
        r.fail("go test: %d test(s) fail that the base tree passed, and fail again "
               "on %d isolated re-run(s) of their own:\n    %s",
               len(new_tests), gates.CONFIRMATIONS, "\n    ".join(new_tests[:20]))
    else:
        r.ok("go test green on %s and %s in ./store/ (baseline: %d pre-existing failure(s)%s)",
             " ".join(gates.TEST_PACKAGES), gates.STORE_RUN, len(base["tests"]),
             "; %d of them now pass" % len(fixed) if fixed else "")

for entry in now["unconfirmed"]:
    r.ok("%s did not survive being asked again; not charged", entry)
for what, why in sorted(now["notes"].items()):
    print("  note  %s -- %s" % (what, why))

r.finish()
