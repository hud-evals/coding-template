"""Criterion 3 -- the floor. Blocker.

The ticket asks for one thing: "restoring it gives you what restoring a
whole-database backup would have given you, minus the tables you did not ask
for". This criterion checks the part of that which every competent attempt
gets right, and it is deliberately cheap: a file that arrives, loads, and holds
the rows it was asked for.

For every (fixture, subset) pair:
  * Dump returns no error and does not panic;
  * the file loads under the sqlite3 binary with an empty stderr and rc 0;
  * the same file loads through the repo's own restore path too, and the two
    databases that come out are the same one: same schema objects, same
    tables, same rows, same counters. The ticket says "the same file has to
    produce the same database whether sqlite3 reads it or our own restore path
    does", and that is the whole of the sentence;
  * each requested table holds exactly the rows it held in the original.

What the restored database DOES with those tables is criterion 4's question,
and it is asked there by comparing answers rather than by checking for
success -- so a database that was broken before the backup is not charged to
the run here either.

The odd requests the HTTP surface passes through are checked as leg L10 of
criterion 5, not here: they are worth a leg, not a cap on the whole reward.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.environ.get("GRADER_DIR", ""), "lib") or "lib")
import checkbase as cb  # noqa: E402
import oracle  # noqa: E402


def same_database(repo_db, sqlite3_path):
    """The two readers have to end up with the same database. Returns the
    first disagreement, or "".

    The repo's reader ran in the Go driver; this compares what it left behind
    with what the sqlite3 binary produced from the very same bytes.
    """
    if not repo_db or not os.path.exists(repo_db):
        return "the repo's own restore path produced no database"
    other = oracle.connect(repo_db)
    mine = oracle.connect(sqlite3_path)
    try:
        if oracle.object_signatures(other) != oracle.object_signatures(mine):
            return "the two readers ended up with different schema objects"
        tables = sorted(t["name"] for t in oracle.real_tables(other))
        if tables != sorted(t["name"] for t in oracle.real_tables(mine)):
            return "the two readers ended up with different tables"
        for t in tables:
            if oracle.canonical_rows(other, t) != oracle.canonical_rows(mine, t):
                return "the two readers ended up with different rows in %s" % t
        if oracle.sequence_rows(other) != oracle.sequence_rows(mine):
            return "the two readers ended up with different counters"
        return ""
    except sqlite3.Error as e:
        return "reading back what the repo's restore path wrote failed: %s" % e
    finally:
        other.close()
        mine.close()


r = cb.Report("criterion 3: the subset arrives, restores under both readers, rows exact")
results = cb.produce()

for pid in sorted(cb.PAIRS):
    p = cb.PAIRS[pid]
    res = results[pid]
    path, why = cb.restore_pair(res)
    if path is None:
        r.fail("%s: %s", pid, why)
        continue

    if res.get("repo_error"):
        r.fail("%s: the repo's own restore path rejects the same file: %s",
               pid, res["repo_error"])
        continue

    why = same_database(res.get("repo_restored"), path)
    if why:
        r.fail("%s: the two readers do not agree on what the file says: %s", pid, why)
        continue

    conn = oracle.connect(path)
    try:
        bad = False
        for table, want in sorted(p["rows"].items()):
            try:
                got = oracle.canonical_rows(conn, table)
            except sqlite3.Error as e:
                r.fail("%s: table %s did not come back: %s", pid, table, e)
                bad = True
                continue
            if got != want:
                r.fail("%s: rows of %s differ (%d rows, expected %d)",
                       pid, table, len(got), len(want))
                bad = True
        if bad:
            continue
        missing = [t for t in p["subset_tables"] if not oracle.table_exists(conn, t)]
        if missing:
            r.fail("%s: %s missing from the restored database", pid, missing)
            continue
    finally:
        conn.close()

    r.ok("%s: restores under both readers, %d table(s) exact", pid, len(p["subset_tables"]))

r.finish()
