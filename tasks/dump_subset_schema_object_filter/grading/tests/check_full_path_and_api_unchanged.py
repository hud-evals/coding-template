"""Criterion 2 -- the declared scope. Gate: green on the untouched tree.

The ticket says two things this check enforces, in its own words:

  "A backup with no tables= must come out byte for byte as it does today,
   warts and all. This ticket is about the subset case."
  "The exported shape of the dump API stays as it is -- Dump(w io.Writer,
   tableNames ...string) and the HTTP surface. Existing callers must keep
   compiling."

So: every fixture's whole-database dump is compared byte for byte against the
output the untouched tree produced when the image was built -- including the
two inherited bugs of the full path (the virtual table whose shadow tables it
re-creates, and the DELETE FROM sqlite_sequence it emits before the table that
owns the counter exists). Warts and all means warts and all: fixing them here
is out of scope and is not rewarded.

The API shape is enforced by construction: grader/gohar declares the exported
signatures it depends on and simply stops compiling if any of them moves. If
the driver built, the shape held.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import checkbase as cb  # noqa: E402

r = cb.Report("criterion 2: full-dump path frozen, dump API shape unchanged")

results = cb.produce()  # building this at all is the API-shape assertion
r.ok("the dump driver compiles against the tree: exported API shape intact")

for name in sorted(cb.FULL):
    want = cb.FULL[name]
    res = results["full__" + name]
    if res.get("panic"):
        r.fail("%s: the full-dump path panicked: %s", name, res["panic"])
        continue
    if res.get("dump_error"):
        r.fail("%s: the full-dump path now returns an error: %s", name, res["dump_error"])
        continue
    got = cb.sha256_file(res["dump"])
    size = os.path.getsize(res["dump"])
    if got != want["sha256"]:
        frozen = os.path.join(cb.FULL_DUMPS, name + ".sql")
        detail = ""
        try:
            import difflib
            a = open(frozen).read().splitlines(keepends=True)
            b = open(res["dump"]).read().splitlines(keepends=True)
            detail = "".join(list(difflib.unified_diff(a, b, "frozen", "now"))[:24])
        except Exception:  # pragma: no cover - diagnostics only
            pass
        r.fail("%s: whole-database dump changed (%d bytes, was %d)\n%s",
               name, size, want["bytes"], detail)
    else:
        r.ok("%s: whole-database dump byte-identical (%d bytes)", name, size)

r.finish()
