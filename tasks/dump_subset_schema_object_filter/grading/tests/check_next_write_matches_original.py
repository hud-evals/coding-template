"""Criterion 6 -- what the database does next.

The ticket: "the same thing next: what the restored database does on the
following write is what the original would have done."

Two halves, both measured by running the database rather than by reading it:

  * the counter rows of the restored database are exactly the counter rows the
    requested tables owned in the original -- a row belonging to a table
    outside the subset is something the original would not have had, and a
    missing row makes the restored database hand out a key the original
    already gave away;
  * an actual INSERT into each of those tables hands out the key the original
    would have handed out next. The INSERT is rolled back.

Fixtures with no autoincrementing table in the subset must come back with no
counter rows at all.

Weight 0.00, and a blocker -- two separate answers to two separate questions
(see tasks.py). Weight, because the measurement says every realistic wrong
solution passes this: parked weight on a check nobody fails is weight that
lifts every wrong run toward the gate. Blocking, because a database that hands
out a key it already handed out is wrong data, not an incomplete feature. The
work itself is still scored: the counters are leg L9 inside criterion 5, so a
run that forgets them still loses that share of the gradient.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import checkbase as cb  # noqa: E402
import oracle  # noqa: E402

r = cb.Report("criterion 6: the restored database hands out the next key the original would")
results = cb.produce()

for pid in sorted(cb.PAIRS):
    p = cb.PAIRS[pid]
    path, why = cb.restore_pair(results[pid])
    if path is None:
        r.fail("%s: %s", pid, why)
        continue
    conn = oracle.connect(path)
    try:
        want = {k: int(v) for k, v in p["seq"].items()}
        got = oracle.sequence_rows(conn)
        if got != want:
            missing = {k: v for k, v in want.items() if k not in got}
            extra = {k: v for k, v in got.items() if k not in want}
            wrong = {k: (got[k], want[k]) for k in want if k in got and got[k] != want[k]}
            r.fail("%s: counters wrong -- missing %s, leaked %s, off %s",
                   pid, missing, extra, wrong)
            continue

        bad = None
        for table, key in sorted(p["next_key"].items()):
            try:
                handed = oracle.next_key(conn, table)
            except sqlite3.Error as e:
                bad = "inserting into %s failed: %s" % (table, e)
                break
            if handed != int(key):
                bad = ("the next key of %s is %d, but the original would have handed "
                       "out %d" % (table, handed, int(key)))
                break
        if bad:
            r.fail("%s: %s", pid, bad)
            continue

        if want:
            r.ok("%s: counters %s, next keys %s", pid, want, p["next_key"])
        else:
            r.ok("%s: no counters, as the original had none for this subset", pid)
    finally:
        conn.close()

r.finish()
