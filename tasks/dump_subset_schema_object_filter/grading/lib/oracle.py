"""Execution helpers shared by the corpus builder and the hidden checks.

Everything here is mechanical: build a database, restore a dump with the
sqlite3 binary, read what came back, poke it. No judgement, no parsing of SQL
-- the only authority on what an object needs is SQLite itself, asked by
running the statement that would use it.

Every question is asked twice -- once of the original database, once of the
one a dump restored -- and it is the two ANSWERS that are compared, never one
answer checked for success. A database that was broken before it was backed up
has to come back broken; "it works now" is a different database, not a restored
one.

Two facts the probes lean on (both verified by execution, not assumed):

* SQLite resolves a trigger's whole body when it *prepares* the DML on the
  trigger's table, not when the trigger fires. So ``DELETE FROM t WHERE 0``
  and ``INSERT INTO t SELECT * FROM t WHERE 0`` are enough to prove a trigger
  can run, and they change nothing -- the probes have no side effects at all.
* A view is compiled when it is selected from, so ``SELECT * FROM v`` proves
  every table the view reaches is present, however deeply it is buried.
"""

import os
import re
import sqlite3
import subprocess

SQLITE3 = os.environ.get("GRADER_SQLITE3", "sqlite3")

INTERNAL = re.compile(r"^sqlite_", re.I)


def connect(path):
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    conn.text_factory = bytes
    return conn


def connect_text(path):
    """A connection whose values come back as str, for comparing answers."""
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    conn.text_factory = str
    return conn


def outcome(conn, stmt):
    """What a database says when asked: ["ok", rows] or ["err", message].

    This is the unit every relativised comparison is made in. Rows are sorted
    reprs, so storage order is not an answer.
    """
    try:
        cur = conn.execute(stmt)
        return ["ok", sorted(repr(r) for r in cur.fetchall())]
    except sqlite3.Error as e:
        return ["err", str(e)]


def view_outcome(conn, view):
    return outcome(conn, 'SELECT * FROM "%s"' % view.replace('"', '""'))


def probe_statements(conn, target):
    """The three writes whose preparation resolves every trigger hanging on
    the target. Worked out once, on the original, so that both databases are
    asked the very same questions."""
    q = target.replace('"', '""')
    cols = columns(conn, target)
    out = ['INSERT INTO "%s" SELECT * FROM "%s" WHERE 0' % (q, q),
           'DELETE FROM "%s" WHERE 0' % q]
    plain = [c for c in cols if not c["pk"]] or cols
    if plain:
        c = plain[0]["name"].replace('"', '""')
        out.append('UPDATE "%s" SET "%s" = "%s" WHERE 0' % (q, c, c))
    return out


def probe_answers(path, stmts):
    """Run the frozen questions against a database and collect the answers.
    Everything happens inside a transaction that is rolled back, so the probes
    have no effect at all."""
    conn = connect_text(path)
    got = []
    conn.execute("BEGIN")
    try:
        for s in stmts:
            got.append(outcome(conn, s))
    finally:
        conn.execute("ROLLBACK")
        conn.close()
    return got


def _text(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", "surrogateescape")
    return v


def build_database(path, statements):
    """Create a database from a frozen statement list, one statement at a time."""
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    try:
        for stmt in statements:
            conn.execute(stmt)
    finally:
        conn.close()


# ─── reading a database ────────────────────────────────────────────────────


def schema_objects(conn):
    """Indexes, triggers and views in sqlite_master order (== creation order).

    SQLite's own bookkeeping (sqlite_autoindex_*, sqlite_stat1, ...) is left
    out: none of it is written by a dump, and SPEC 3.3 cuts it from the
    punishing corpus.
    """
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE type IN ('index','trigger','view') AND sql IS NOT NULL"
    ).fetchall()
    out = []
    for typ, name, tbl, sql in rows:
        typ, name, tbl, sql = _text(typ), _text(name), _text(tbl), _text(sql)
        if INTERNAL.match(name):
            continue
        out.append({"type": typ, "name": name, "tbl_name": tbl, "sql": sql})
    return out


def real_tables(conn):
    """User tables, in sqlite_master order. Virtual tables are out of scope."""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
    ).fetchall()
    out = []
    for name, sql in rows:
        name, sql = _text(name), _text(sql)
        if INTERNAL.match(name):
            continue
        if re.match(r"^\s*CREATE\s+VIRTUAL\s+TABLE", sql, re.I):
            continue
        out.append({"name": name, "sql": sql})
    return out


def table_exists(conn, name):
    n = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()[0]
    return n > 0


def normalise_sql(sql):
    """Collapse runs of whitespace. Nothing else: sqlite_master keeps the text
    of a CREATE statement verbatim, so a dump that carried the object through
    reproduces it character for character."""
    return " ".join(sql.split())


def object_signatures(conn):
    """(type, name, normalised sql) for every schema object, sorted -- the
    comparison unit of criterion 4. Order is checked separately (leg L8):
    a different but still loadable replay order is not an error."""
    return sorted(
        (o["type"], o["name"], normalise_sql(o["sql"])) for o in schema_objects(conn)
    )


def object_order(conn):
    return [o["name"] for o in schema_objects(conn)]


def columns(conn, name):
    rows = conn.execute('PRAGMA table_info("%s")' % name.replace('"', '""')).fetchall()
    return [
        {"name": _text(r[1]), "type": _text(r[2]) or "", "notnull": r[3], "pk": r[5]}
        for r in rows
    ]


def canonical_rows(conn, table):
    """Every row rendered through quote(), sorted: two databases compare
    without caring about storage order or Python's type mapping."""
    cols = columns(conn, table)
    if not cols:
        raise sqlite3.Error("no such table: %s" % table)
    expr = "||'|'||".join('quote("%s")' % c["name"].replace('"', '""') for c in cols)
    rows = conn.execute('SELECT %s FROM "%s"' % (expr, table.replace('"', '""'))).fetchall()
    return sorted(_text(r[0]) if r[0] is not None else "" for r in rows)


def sequence_rows(conn):
    if not table_exists(conn, "sqlite_sequence"):
        return {}
    rows = conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
    return {_text(n): int(s) for n, s in rows}


# ─── probes ────────────────────────────────────────────────────────────────


def next_key(conn, table):
    """The rowid the next INSERT into an AUTOINCREMENT table hands out. Rolled
    back, so nothing the caller sees afterwards has moved."""
    q = table.replace('"', '""')
    cols = columns(conn, table)
    names, vals = [], []
    for i, c in enumerate(cols):
        if c["pk"]:
            continue
        names.append('"%s"' % c["name"].replace('"', '""'))
        up = (c["type"] or "").upper()
        if "INT" in up:
            vals.append("900001")
        elif "REAL" in up or "FLOA" in up or "DOUB" in up:
            vals.append("1.5")
        else:
            vals.append("'probe'")
    conn.execute("BEGIN")
    try:
        if names:
            stmt = 'INSERT INTO "%s" (%s) VALUES (%s)' % (q, ",".join(names), ",".join(vals))
        else:
            stmt = 'INSERT INTO "%s" DEFAULT VALUES' % q
        cur = conn.execute(stmt)
        return int(cur.lastrowid)
    finally:
        conn.execute("ROLLBACK")


# ─── restoring ─────────────────────────────────────────────────────────────


def judge_matches_original(path, expected):
    """The criterion-4 predicate, in one place so the corpus builder and the
    hidden check cannot drift apart.

    A restored database matches the original when three things hold, and every
    one of them is a comparison of two answers rather than a test for success:

      * its schema objects are exactly the reference set, each carried through
        with its text as it was;
      * every view answers exactly what it answered in the original -- the same
        rows, or the same error;
      * every requested table answers the frozen write probes exactly as the
        original answers them, so a trigger that came back broken was broken
        before, and one that came back working was working before.

    Returns (ok, reason).
    """
    conn = connect_text(path)
    try:
        want = sorted((o["type"], o["name"], o["nsql"]) for o in expected["objects"])
        got = object_signatures(conn)
        if got != want:
            wnames = {(t, n) for t, n, _ in want}
            gnames = {(t, n) for t, n, _ in got}
            lost = sorted(n for _t, n in wnames - gnames)
            leaked = sorted(n for _t, n in gnames - wnames)
            mangled = sorted(n for t, n, s in got
                             if (t, n) in wnames and (t, n, s) not in set(want))
            return False, ("object set wrong -- %d lost %s, %d leaked %s, %d altered %s"
                           % (len(lost), lost[:8], len(leaked), leaked[:8],
                              len(mangled), mangled[:8]))
        for view, expect in sorted(expected["views"].items()):
            here = view_outcome(conn, view)
            if here != expect:
                return False, ("view %s answers %s, the original answers %s"
                               % (view, _short(here), _short(expect)))
    finally:
        conn.close()

    for table, frozen in sorted(expected["table_probes"].items()):
        stmts = [q for q, _a in frozen]
        want = [a for _q, a in frozen]
        got = probe_answers(path, stmts)
        for q, w, g in zip(stmts, want, got):
            if w != g:
                return False, ("%s answers %s, the original answers %s"
                               % (q, _short(g), _short(w)))
    return True, ""


def _short(ans):
    kind, body = ans[0], ans[1]
    if kind == "err":
        return "the error %r" % body
    return "%d row(s)" % len(body)


def restore(dump_path, dst):
    """Load a dump into an empty database with the sqlite3 binary.

    The external loader is the point: the artefact has to be portable, and the
    repo's own reader must not be the one grading it. Returns (rc, stderr).
    """
    if os.path.exists(dst):
        os.remove(dst)
    with open(dump_path, "rb") as fh:
        proc = subprocess.run(
            [SQLITE3, dst], stdin=fh, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=120,
        )
    return proc.returncode, proc.stderr.decode("utf-8", "replace").strip()
