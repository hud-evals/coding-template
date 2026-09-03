"""Record what the repo's own gates say about an untouched checkout.

Run inside the image, against the pristine tree, while the image is being
built: the answer depends on the toolchain that is pinned there, and on nothing
the agent does. The grader subtracts this from what it measures, so a failure
the base already had is never charged to a run.

Usage:
    python3 tools/record_gates.py /path/to/untouched/checkout
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import gates  # noqa: E402

OUT = os.path.join(ROOT, "data", "gates_baseline.json")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    repo = os.path.abspath(sys.argv[1])
    print("recording the repo's own gates over %s" % repo)
    # No baseline is passed in: nothing is confirmed away here.  A failure the
    # pristine tree produced even once belongs in the record, because the
    # record is what gets subtracted from every run later -- erring towards
    # the agent is the whole point of it.
    full = gates.collect(repo)
    if full["unmeasured"]:
        raise SystemExit(
            "a gate never finished while the baseline was being recorded; a "
            "half-measured baseline would charge runs for the gap:\n  "
            + "\n  ".join("%s: %s" % kv for kv in sorted(full["unmeasured"].items())))
    base = {k: full[k] for k in ("build", "gofmt", "vet", "tests")}
    if base["build"]:
        raise SystemExit("the untouched tree does not build; the image is broken:\n"
                         + "\n".join(base["build"]))
    with open(OUT, "w") as fh:
        json.dump(base, fh, indent=1, sort_keys=True)
    print("  gofmt      %d file(s) already unformatted" % len(base["gofmt"]))
    print("  go vet     %d line(s) already reported" % len(base["vet"]))
    print("  go test    %d test(s) already failing:" % len(base["tests"]))
    for t in base["tests"]:
        print("               %s" % t)
    print("-> %s" % OUT)


if __name__ == "__main__":
    main()
