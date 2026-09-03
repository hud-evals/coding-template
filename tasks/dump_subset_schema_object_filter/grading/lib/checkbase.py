"""Plumbing every hidden check shares.

Each check gets the same picture: the frozen expectations, one dump per job
produced by the tree under test, and each of those dumps restored into an empty
database with the sqlite3 binary. The checks themselves only compare.
"""

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GRADER_DIR = os.environ.get("GRADER_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

import driver  # noqa: E402
import oracle  # noqa: E402

EXPECTED_PATH = os.path.join(GRADER_DIR, "data", "expected.json")
FIXTURES = os.path.join(GRADER_DIR, "data", "fixtures")
FULL_DUMPS = os.path.join(GRADER_DIR, "data", "full_dumps")

with open(EXPECTED_PATH) as _fh:
    EXPECTED = json.load(_fh)

PAIRS = EXPECTED["pairs"]
ODD = EXPECTED["odd"]
FULL = EXPECTED["full_dumps"]
LEGS = EXPECTED["legs"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_fixtures():
    """The corpus is part of the grader, not of the workspace. If a byte of it
    has moved, nothing downstream means anything."""
    for name, digest in EXPECTED["fixtures"].items():
        path = os.path.join(FIXTURES, name + ".sqlite")
        if not os.path.exists(path) or sha256_file(path) != digest:
            raise SystemExit("GRADER FIXTURE TAMPERED: %s" % name)


def all_jobs():
    jobs = []
    for pid, p in sorted(PAIRS.items()):
        jobs.append({"id": pid, "fixture": p["fixture"], "subset": p["subset"],
                     "restore": True})
    for o in ODD:
        jobs.append({"id": o["id"], "fixture": o["fixture"], "subset": o["subset"],
                     "restore": True})
    for f in sorted(FULL):
        jobs.append({"id": "full__" + f, "fixture": f, "subset": [], "restore": False})
    return jobs


def produce():
    """Every dump the corpus asks for, from the tree under test."""
    verify_fixtures()
    return driver.run_jobs(all_jobs(), label="all")


def restore_dir():
    state = os.environ.get("GRADER_STATE_DIR") or os.path.join(GRADER_DIR, ".calib", "state")
    path = os.path.join(state, "restored")
    os.makedirs(path, exist_ok=True)
    return path


def restore_pair(result):
    """(path of the restored database or None, reason). A dump that did not
    load has no database."""
    if result.get("panic"):
        return None, "the dump path panicked: %s" % result["panic"]
    if result.get("dump_error"):
        return None, "Dump returned an error: %s" % result["dump_error"]
    dst = os.path.join(restore_dir(), result["id"] + ".db")
    rc, stderr = oracle.restore(result["dump"], dst)
    if rc != 0 or stderr:
        return None, "the dump does not load: rc=%d %s" % (rc, stderr.splitlines()[0] if stderr else "")
    return dst, ""


class Report:
    """Prints as it goes and remembers the verdict. Output is bounded: the
    grade frame carries the tail of stdout, not an essay."""

    def __init__(self, title, cap=60):
        self.title = title
        self.cap = cap
        self.failures = []
        self.passes = 0
        print("== %s" % title)

    def ok(self, fmt, *args):
        self.passes += 1
        print("  ok    " + (fmt % args if args else fmt))

    def fail(self, fmt, *args):
        msg = fmt % args if args else fmt
        self.failures.append(msg)
        if len(self.failures) <= self.cap:
            print("  FAIL  " + msg)

    def finish(self, score=None):
        if self.failures:
            print("\n%d checks failed, %d passed" % (len(self.failures), self.passes))
        else:
            print("\nall %d checks passed" % self.passes)
        if score is not None:
            print("GRADER_SCORE %.6f" % score)
            sys.exit(0 if score >= 1.0 - 1e-9 else 1)
        sys.exit(1 if self.failures else 0)
