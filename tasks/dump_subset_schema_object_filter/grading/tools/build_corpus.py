"""Freeze the corpus and the expectations. Run once, outside the container.

The expectations are not read off any implementation. For every (fixture,
subset) pair this script works out, by experiment, the largest set of schema
objects for which the restored database ANSWERS AS THE ORIGINAL DOES:

    start with every schema object of the fixture, build a database holding
    only the requested tables plus those objects, and throw away whatever
    answers differently from the original -- an object that will not create, a
    view that returns other rows or fails where the original succeeded (or
    succeeds where the original failed), a trigger whose table stops answering
    the way it answered before. Repeat until nothing more falls out.

Everything is decided by running SQLite twice, once on each side. Nothing is
parsed. The difference from "the greatest set that works" is the whole point:
an object already broken in the original has to come back broken, because a
backup copies a database and does not repair one.

That set is then proved to be the answer, both ways:

  * it holds -- every view answers what it answered, every requested table
    answers the write probes exactly as the original answers them;
  * it is maximal -- adding back any object that was thrown away changes one of
    those answers, so nothing that could have come along was left behind.

Where the corpus states a hand-written answer, the experiment must agree with
it or the corpus is refused: the reference must not be a second, unreviewed
implementation of the gold.

Attribution for triggers is by isolation on BOTH sides: a trigger is judged on
a copy holding only it, against an original stripped to only it, so a
difference can never be blamed on a neighbour that was legitimately left
behind.

Usage:
    python3 tools/build_corpus.py --base-tree /path/to/untouched/checkout
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import corpus  # noqa: E402
import oracle  # noqa: E402
import driver  # noqa: E402

FIXTURES = os.path.join(ROOT, "data", "fixtures")
FULL_DUMPS = os.path.join(ROOT, "data", "full_dumps")
EXPECTED = os.path.join(ROOT, "data", "expected.json")


# ─── building databases ────────────────────────────────────────────────────


def make_db(path, src, tables, objects):
    """Requested tables plus their rows plus the given objects, in order.

    Returns the names of objects that would not create."""
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    # Rows are carried across by reading and writing, not by ATTACH: a view
    # that says main.users cannot live in an attached database, and F1 has one.
    srcraw = sqlite3.connect(src)
    srcraw.isolation_level = None
    failed = []
    try:
        srcconn = oracle.connect(src)
        by_name = {t["name"]: t["sql"] for t in oracle.real_tables(srcconn)}
        seq = oracle.sequence_rows(srcconn)
        srcconn.close()
        for t in tables:
            conn.execute(by_name[t])
            q = t.replace('"', '""')
            data = srcraw.execute('SELECT * FROM "%s"' % q).fetchall()
            if data:
                marks = ",".join("?" * len(data[0]))
                conn.executemany('INSERT INTO "%s" VALUES (%s)' % (q, marks), data)
        # Counters: a correct backup carries them, so the reference database
        # the expectations are read off has to carry them too.
        wanted = {t: seq[t] for t in tables if t in seq}
        if wanted and oracle.table_exists(conn, "sqlite_sequence"):
            conn.execute("DELETE FROM sqlite_sequence")
            for name, value in wanted.items():
                conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                             (name, value))
        for o in objects:
            try:
                conn.execute(o["sql"])
            except sqlite3.Error:
                failed.append(o["name"])
    finally:
        srcraw.close()
        conn.close()
    return failed


def stripped_original(tmp, src, keep_trigger, all_objects):
    """A copy of the original holding exactly one trigger: the baseline that
    trigger is judged against."""
    path = os.path.join(tmp, "orig_iso.sqlite")
    if os.path.exists(path):
        os.remove(path)
    shutil.copyfile(src, path)
    conn = oracle.connect_text(path)
    try:
        for o in all_objects:
            if o["type"] == "trigger" and o["name"] != keep_trigger:
                conn.execute('DROP TRIGGER "%s"' % o["name"].replace('"', '""'))
    finally:
        conn.close()
    return path


def read_original(tmp, src, tables, all_objects):
    """What the original answers. Everything downstream is compared to this."""
    conn = oracle.connect_text(src)
    views = {}
    for o in all_objects:
        if o["type"] == "view":
            views[o["name"]] = oracle.view_outcome(conn, o["name"])
    stmts = {t: oracle.probe_statements(conn, t) for t in tables
             if oracle.table_exists(conn, t)}
    conn.close()

    tables_ans = {t: oracle.probe_answers(src, q) for t, q in stmts.items()}

    trig = {}
    for o in all_objects:
        if o["type"] != "trigger":
            continue
        base = stripped_original(tmp, src, o["name"], all_objects)
        bconn = oracle.connect_text(base)
        known = bconn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name=? AND type IN ('table','view')",
            (o["tbl_name"],)).fetchone()[0]
        q = oracle.probe_statements(bconn, o["tbl_name"]) if known else []
        bconn.close()
        if not known:
            continue
        trig[o["name"]] = (q, oracle.probe_answers(base, q))
    return {"views": views, "table_stmts": stmts, "tables": tables_ans, "triggers": trig}


def answers_as_original(path, kept, base, tables):
    """First object whose answers differ from the original's, or "". Views
    first, then triggers, each isolated the same way the baseline was."""
    conn = oracle.connect_text(path)
    try:
        for o in kept:
            if o["type"] != "view":
                continue
            if oracle.view_outcome(conn, o["name"]) != base["views"][o["name"]]:
                return o["name"]
    finally:
        conn.close()
    return ""


def closure(tmp, src, tables, all_objects, base):
    """The largest set of objects the restored database answers alike on."""
    kept = list(all_objects)
    path = os.path.join(tmp, "closure.sqlite")
    iso = os.path.join(tmp, "iso.sqlite")
    while True:
        failed = make_db(path, src, tables, kept)
        if failed:
            kept = [o for o in kept if o["name"] not in failed]
            continue

        bad = answers_as_original(path, kept, base, tables)
        if bad:
            kept = [o for o in kept if o["name"] != bad]
            continue

        others = [o for o in kept if o["type"] != "trigger"]
        for o in kept:
            if o["type"] != "trigger":
                continue
            if make_db(iso, src, tables, others + [o]):
                bad = o["name"]
                break
            if o["name"] not in base["triggers"]:
                continue
            stmts, want = base["triggers"][o["name"]]
            if oracle.probe_answers(iso, stmts) != want:
                bad = o["name"]
                break
        if bad:
            kept = [o for o in kept if o["name"] != bad]
            continue

        # An assertion, not an attribution: with everything that survived in
        # place the requested tables have to answer exactly as they did. A
        # reference that cannot manage that is not a reference.
        make_db(path, src, tables, kept)
        for t, stmts in base["table_stmts"].items():
            if oracle.probe_answers(path, stmts) != base["tables"][t]:
                raise SystemExit(
                    "the reference is not self-consistent on %s: the copy and the "
                    "original answer the write probes differently" % t)
        return kept


def prove_maximal(tmp, src, tables, kept, dropped, base):
    """Every dropped object must genuinely change an answer when added back."""
    path = os.path.join(tmp, "maximal.sqlite")
    iso = os.path.join(tmp, "max_iso.sqlite")
    harmless = []
    others = [o for o in kept if o["type"] != "trigger"]
    for o in dropped:
        if o["name"] in make_db(path, src, tables, kept + [o]):
            continue                                  # will not even create
        if o["type"] == "view":
            conn = oracle.connect_text(path)
            got = oracle.view_outcome(conn, o["name"])
            conn.close()
            if got != base["views"][o["name"]]:
                continue                              # answers differently
        elif o["type"] == "trigger":
            if o["name"] not in base["triggers"]:
                harmless.append(o["name"])
                continue
            if make_db(iso, src, tables, others + [o]):
                continue
            stmts, want = base["triggers"][o["name"]]
            if oracle.probe_answers(iso, stmts) != want:
                continue
        # last resort: it changes what the requested tables answer
        changed = False
        for t, stmts in base["table_stmts"].items():
            if oracle.probe_answers(path, stmts) != base["tables"][t]:
                changed = True
                break
        if not changed:
            harmless.append(o["name"])
    return harmless


# ─── the corpus ────────────────────────────────────────────────────────────


def build_fixtures():
    os.makedirs(FIXTURES, exist_ok=True)
    digests = {}
    for name, stmts in corpus.FIXTURES.items():
        path = os.path.join(FIXTURES, name + ".sqlite")
        oracle.build_database(path, stmts)
        digests[name] = hashlib.sha256(open(path, "rb").read()).hexdigest()
        print("  fixture %-12s %s" % (name, digests[name][:16]))
    return digests


def build_pair(tmp, fixture, subset, hand):
    src = os.path.join(FIXTURES, fixture + ".sqlite")
    srcconn = oracle.connect(src)
    all_objects = oracle.schema_objects(srcconn)
    src_tables = {t["name"] for t in oracle.real_tables(srcconn)}
    # The subset as handed to the tree under test may repeat a name or carry
    # names that are not tables ("a repeated name, an empty one, a name that
    # is not a table"); the reference database is built from the tables the
    # request effectively names, each once.
    tables = list(dict.fromkeys(t for t in subset if t in src_tables))
    seq = oracle.sequence_rows(srcconn)
    rows = {t: oracle.canonical_rows(srcconn, t) for t in tables}
    srcconn.close()

    base = read_original(tmp, src, tables, all_objects)
    kept = closure(tmp, src, tables, all_objects, base)
    kept_names = {o["name"] for o in kept}
    dropped = [o for o in all_objects if o["name"] not in kept_names]

    # Self-verification, both directions.
    path = os.path.join(tmp, "verify.sqlite")
    failed = make_db(path, src, tables, kept)
    if failed:
        raise SystemExit("%s %s: the answer does not even build: %s" % (fixture, subset, failed))
    bad = answers_as_original(path, kept, base, tables)
    if bad:
        raise SystemExit("%s %s: the answer does not hold: %s answers differently"
                         % (fixture, subset, bad))
    harmless = prove_maximal(tmp, src, tables, kept, dropped, base)
    if harmless:
        raise SystemExit("%s %s: dropped but harmless, so the answer is not maximal: %s"
                         % (fixture, subset, harmless))

    if hand is not None and sorted(hand) != sorted(kept_names):
        raise SystemExit(
            "%s %s: the hand answer and the experiment disagree\n  hand only  %s\n"
            "  exp only   %s" % (fixture, subset,
                                 sorted(set(hand) - kept_names),
                                 sorted(kept_names - set(hand))))

    wanted_seq = {t: seq[t] for t in tables if t in seq}

    # The key the ORIGINAL hands out next, measured by handing one out and
    # rolling it back. A table whose insert the original itself refuses is left
    # out: the restored database is owed the original's behaviour, not a
    # working one.
    next_key = {}
    srcconn = oracle.connect(src)
    try:
        for t in wanted_seq:
            try:
                k = oracle.next_key(srcconn, t)
            except sqlite3.Error:
                continue
            if k != wanted_seq[t] + 1:
                raise SystemExit("%s %s: the original hands out %d after a counter of %d"
                                 % (fixture, subset, k, wanted_seq[t]))
            next_key[t] = k
    finally:
        srcconn.close()

    return {
        "fixture": fixture,
        "subset": subset,
        "subset_tables": tables,
        "objects": [
            {"type": o["type"], "name": o["name"], "tbl_name": o["tbl_name"],
             "nsql": oracle.normalise_sql(o["sql"])}
            for o in kept
        ],
        "order": [o["name"] for o in kept],
        "rows": rows,
        # What the ORIGINAL answers -- the restored database is held to these,
        # errors included.
        "views": {o["name"]: base["views"][o["name"]] for o in kept if o["type"] == "view"},
        "table_probes": {t: list(zip(base["table_stmts"][t], base["tables"][t]))
                         for t in base["table_stmts"]},
        "seq": wanted_seq,
        "next_key": next_key,
        "hand_checked": hand is not None,
    }


def freeze_full_dumps(base_tree, state):
    """The whole-database dump of the untouched tree, warts and all."""
    shutil.rmtree(FULL_DUMPS, ignore_errors=True)
    os.makedirs(FULL_DUMPS)
    jobs = [{"id": f, "fixture": f, "subset": [], "restore": False}
            for f in corpus.FULL_DUMP_FIXTURES]
    results = driver.run_jobs(jobs, repo=base_tree, state=state,
                              fixtures=FIXTURES, label="baseline")
    out = {}
    for f in corpus.FULL_DUMP_FIXTURES:
        r = results[f]
        if r["dump_error"] or r["panic"]:
            raise SystemExit("base tree failed to dump %s: %s %s"
                             % (f, r["dump_error"], r["panic"]))
        data = open(r["dump"], "rb").read()
        shutil.copyfile(r["dump"], os.path.join(FULL_DUMPS, f + ".sql"))
        out[f] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        print("  full dump %-12s %6d bytes  %s" % (f, len(data), out[f]["sha256"][:16]))
    return out


def base_pass_pairs(base_tree, state, pairs):
    """Which pairs the untouched tree already answers correctly.

    Those are the anti-vacuum controls of criterion 4 -- a subset that happens
    to be the whole database, or a fixture whose every object needs only the
    requested table. They earn nothing (a criterion green on an untouched
    checkout cannot carry weight); they exist so that throwing every view and
    trigger away is not a way to pass.
    """
    jobs = [{"id": pid, "fixture": p["fixture"], "subset": p["subset"], "restore": False}
            for pid, p in sorted(pairs.items())]
    results = driver.run_jobs(jobs, repo=base_tree, state=state,
                              fixtures=FIXTURES, label="basepairs")
    out = []
    restored = os.path.join(state, "base_restored")
    shutil.rmtree(restored, ignore_errors=True)
    os.makedirs(restored)
    for pid, p in sorted(pairs.items()):
        res = results[pid]
        if res["dump_error"] or res["panic"]:
            continue
        dst = os.path.join(restored, pid + ".db")
        rc, stderr = oracle.restore(res["dump"], dst)
        if rc != 0 or stderr:
            continue
        ok, _ = oracle.judge_matches_original(dst, p)
        if ok:
            out.append(pid)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-tree", required=True,
                    help="untouched checkout, the author of the frozen full dumps")
    args = ap.parse_args()

    print("== fixtures")
    digests = build_fixtures()

    print("== expectations")
    pairs = {}
    with tempfile.TemporaryDirectory() as tmp:
        for fixture, subset, hand in corpus.PAIRS:
            pid = corpus.pair_id(fixture, subset)
            pairs[pid] = build_pair(tmp, fixture, subset, hand)
            mark = "hand+experiment" if hand is not None else "experiment"
            print("  %-34s %2d objects  (%s)"
                  % (pid, len(pairs[pid]["objects"]), mark))

    print("== legs")
    check_legs(pairs)

    print("== full dumps from the base tree")
    state = os.path.join(ROOT, ".calib", "corpus")
    os.makedirs(state, exist_ok=True)
    full = freeze_full_dumps(os.path.abspath(args.base_tree), state)

    print("== which pairs the base tree already answers correctly")
    base_pass = base_pass_pairs(os.path.abspath(args.base_tree), state, pairs)
    for pid in base_pass:
        print("  control  %s" % pid)
    earnable = sorted(set(pairs) - set(base_pass))
    print("  %d control pair(s), %d earnable" % (len(base_pass), len(earnable)))
    if not earnable:
        raise SystemExit("no pair is wrong on the base tree: criterion 4 would be free")

    odd = [{"id": corpus.odd_id(s), "fixture": "F6_odd", "subset": s}
           for s in corpus.ODD_SUBSETS]

    with open(EXPECTED, "w") as fh:
        json.dump({"pairs": pairs, "odd": odd, "full_dumps": full,
                   "fixtures": digests, "legs": corpus.LEGS,
                   "base_pass": base_pass}, fh, indent=1, sort_keys=True)
    print("\nfroze %d pairs (%d earnable), %d odd inputs, %d full dumps -> %s"
          % (len(pairs), len(earnable), len(odd), len(full), EXPECTED))


def check_legs(pairs):
    """Every leg has to name a case the corpus actually contains, and every
    presence/absence it claims has to be true of the frozen answer. A leg that
    asserts something the reference itself does not hold is a broken leg."""
    for leg in corpus.LEGS:
        if leg.get("odd"):
            print("  %s ok -- %s" % (leg["id"], leg["what"]))
            continue
        for case in leg["cases"]:
            pid = corpus.pair_id(case["fixture"], case["subset"])
            if pid not in pairs:
                raise SystemExit("leg %s names a pair that is not in the corpus: %s"
                                 % (leg["id"], pid))
            names = {o["name"] for o in pairs[pid]["objects"]}
            for n in case.get("present", []):
                if n not in names:
                    raise SystemExit("leg %s: %s expects %s to be kept, the reference drops it"
                                     % (leg["id"], pid, n))
            for n in case.get("absent", []):
                if n in names:
                    raise SystemExit("leg %s: %s expects %s to be dropped, the reference keeps it"
                                     % (leg["id"], pid, n))
            order = pairs[pid]["order"]
            wanted = [n for n in case.get("order", [])]
            if wanted:
                if any(n not in order for n in wanted):
                    raise SystemExit("leg %s: %s order names an object that is not kept" % (leg["id"], pid))
                idx = [order.index(n) for n in wanted]
                if idx != sorted(idx):
                    raise SystemExit("leg %s: %s order is not the reference order" % (leg["id"], pid))
            for n in case.get("same_error", []):
                if n not in names:
                    raise SystemExit("leg %s: %s expects %s to come back, the reference drops it"
                                     % (leg["id"], pid, n))
                ans = pairs[pid]["views"].get(n)
                if not ans or ans[0] != "err":
                    raise SystemExit("leg %s: %s claims %s is broken in the original, "
                                     "but it answers fine" % (leg["id"], pid, n))
            if "seq" in case and case["seq"] != pairs[pid]["seq"]:
                raise SystemExit("leg %s: %s counters %s != reference %s"
                                 % (leg["id"], pid, case["seq"], pairs[pid]["seq"]))
        print("  %s ok -- %s" % (leg["id"], leg["what"]))


if __name__ == "__main__":
    main()
