"""Criterion 5 -- the named legs of the behaviour. Fractional.

Criterion 4 asks whether the restored database is the original one. This asks
which parts of that were actually worked out, one named case at a time, so a
run that got the shape of the problem and missed a family is not scored the
same as one that dropped every view and called it done.

Every leg is a minimal case of the one thing the ticket asks -- the restored
database answers as the original answered -- and nothing here asks for
anything the ticket does not.

  L1  a view over a view over a view: the chain has to be followed
  L2  an INSTEAD OF trigger belongs to the view it hangs on, not to a table
  L3  a name introduced by a CTE is not a table, and a table it shadows is not
      a dependency
  L4  "users" and main.users are users
  L5  a reference can sit inside a subquery used as an expression
  L6  a trigger needs what its body writes to, not just what it hangs on
  L7  partial, expression and collation indexes on a kept table come along
  L8  what comes back replays in an order the restore can follow (control leg:
      any dump that loads at all satisfies it)
  L9  counters, and no counter row belonging to a table outside the subset
  L10 the odd requests the HTTP surface passes through -- an empty name, a
      repeated one, one of SQLite's own tables, a view's name, a name with a
      semicolon in it. The ticket says such a request is still answered and
      that what must never come back is a file that will not restore, so an
      honest error on one of SQLite's own names counts here exactly as much as
      a file that loads
  L11 identifiers written in [brackets]
  L12 WITH where a reader does not expect it
  L13 syntax SQLite has taken since 3.39
  L14 a view whose table was dropped under it comes back, still failing
  L15 a view naming a column that is not there -- and the case where the
      original's error would not have been the same one
  L16 a trigger that fails on the operation it hangs on comes back
  L17 the chain runs through an object that is already broken
  L18 the subset decides for the broken view: it rides beside its table,
      and stays out of a subset that dropped the table, because "no such
      table" is not the error the original gives
  L19 a subset that names no real table restores an empty database
  L20 two tables kept, a broken view naming a third stays out -- membership
      in the subset, not brokenness, decides
  L21 a view broken by UNION arms of different width: "the same errors where
      the original had errors" is about the error, and 'no such table' is a
      different one
  L22 a view calling a function that does not exist -- same standard
  L23 a view with an ambiguous column across a join -- same standard
  L24 an aggregate misused in WHERE, and a view naming more columns than its
      SELECT yields -- same standard, two more shapes
  L25 a repeated name in tables= is the same subset, same decisions
  L26 an empty name in tables= adds nothing, changes nothing
  L27 a view's own name in tables= names no table
  L28 a name with punctuation in it: its table and view ride, the broken
      view naming a dropped table does not
  L29 counters carried AND the broken view still out: one file answers both
      halves of "the same thing next"

Score = the fraction of legs whose every case is green.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import checkbase as cb  # noqa: E402
import oracle  # noqa: E402

r = cb.Report("criterion 5: the named legs of the restored behaviour")
results = cb.produce()

# One restore per pair, shared by every leg that names it.
restored = {}
for pid in sorted(cb.PAIRS):
    restored[pid] = cb.restore_pair(results[pid])


def check_case(case):
    pid = "%s__%s" % (case["fixture"], "+".join(case["subset"]) if case["subset"] else "ALL")
    path, why = restored[pid]
    if path is None:
        return "%s: %s" % (pid, why)
    conn = oracle.connect(path)
    try:
        names = set(oracle.object_order(conn))
    finally:
        conn.close()
    for n in case.get("present", []):
        if n not in names:
            return "%s: %s was dropped, but the original has it and it belongs" % (pid, n)
    for n in case.get("absent", []):
        if n in names:
            return "%s: %s came back, but the restored database does not answer "\
                   "about it the way the original does" % (pid, n)
    for n in case.get("same_error", []):
        want = cb.PAIRS[pid]["views"][n]
        conn = oracle.connect_text(path)
        try:
            got = oracle.view_outcome(conn, n)
        finally:
            conn.close()
        if got != want:
            return "%s: %s answers %r, the original answers %r" % (
                pid, n, got[0] if got[0] == "ok" else got[1],
                want[0] if want[0] == "ok" else want[1])
    wanted = case.get("order", [])
    if wanted:
        conn = oracle.connect(path)
        try:
            order = oracle.object_order(conn)
        finally:
            conn.close()
        missing = [n for n in wanted if n not in order]
        if missing:
            return "%s: %s missing, so there is no order to check" % (pid, missing)
        idx = [order.index(n) for n in wanted]
        if idx != sorted(idx):
            return "%s: replay order %s does not follow the dependencies" % (
                pid, [order[i] for i in sorted(idx)])
    if "seq" in case:
        conn = oracle.connect(path)
        try:
            got = oracle.sequence_rows(conn)
        finally:
            conn.close()
        if got != case["seq"]:
            return "%s: counters %s, expected %s" % (pid, got, case["seq"])
    return ""


def check_odd():
    """One tables= request the HTTP surface passes through, three possible
    answers: a file that loads (fine), a clear error where the request names
    one of SQLite's own tables (fine -- refusing to invent a backup of the
    bookkeeping is not a broken backup), or a file that does not load (the
    only thing the ticket forbids)."""
    for odd in cb.ODD:
        internal = any(n.lower().startswith("sqlite_") for n in odd["subset"])
        res = results[odd["id"]]
        if res.get("panic"):
            return "tables=%r: the dump path panicked: %s" % (odd["subset"], res["panic"])
        if res.get("dump_error"):
            if internal:
                continue
            return "tables=%r: Dump returned an error: %s" % (
                odd["subset"], res["dump_error"])
        path, why = cb.restore_pair(res)
        if path is None:
            return "tables=%r: %s" % (odd["subset"], why)
        if res.get("repo_error"):
            return "tables=%r: the repo's own restore path rejects it: %s" % (
                odd["subset"], res["repo_error"])
    return ""


green = 0
for leg in cb.LEGS:
    if leg.get("odd"):
        bad = check_odd()
    else:
        bad = ""
        for case in leg["cases"]:
            bad = check_case(case)
            if bad:
                break
    if bad:
        r.fail("%s (%s): %s", leg["id"], leg["what"], bad)
    else:
        green += 1
        r.ok("%s (%s)", leg["id"], leg["what"])

r.finish(score=green / float(len(cb.LEGS)))
