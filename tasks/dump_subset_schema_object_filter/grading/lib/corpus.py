"""Frozen fixture corpus for dump_subset_schema_object_filter.

Mirrors SPEC 3.3/3.4.  Nothing here is random and nothing is read from the
workspace: the schemas are literal, the creation order is significant (it is
the order sqlite_master holds the objects in, and so the order a dump replays
them in), and the pairs are fixed.

``objects`` on a pair, where present, is the answer worked out by hand from the
ticket's rule.  ``tools/build_corpus.py`` recomputes the same answer by
experiment -- greatest fixpoint over "does this object still work" -- and
refuses to freeze a corpus where the two disagree.  Pairs with no hand list are
pinned by the experiment alone, which is the ticket's rule stated as a
procedure.
"""

# ─── fixtures ──────────────────────────────────────────────────────────────

F1_SHOP = [
    "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT)",
    "CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, total REAL)",
    "CREATE TABLE audit (id INTEGER PRIMARY KEY, msg TEXT)",
    "CREATE TABLE prefs (user_id INTEGER PRIMARY KEY, k TEXT, v TEXT) WITHOUT ROWID",

    "CREATE INDEX idx_users_named ON users(name) WHERE name IS NOT NULL",
    "CREATE INDEX idx_users_email_lower ON users(lower(email))",
    "CREATE INDEX idx_audit_msg ON audit(msg)",

    "CREATE VIEW user_names AS SELECT id, name FROM users",
    "CREATE VIEW user_names_upper AS SELECT id, upper(name) AS name FROM user_names",
    "CREATE VIEW user_orders AS SELECT u.name, o.total FROM users u JOIN orders o ON o.user_id = u.id",
    "CREATE VIEW audit_view AS SELECT msg FROM audit",
    "CREATE VIEW user_audit AS SELECT name, (SELECT count(*) FROM audit) AS n FROM users",
    'CREATE VIEW quoted_users AS SELECT name FROM "users"',
    "CREATE VIEW main_users AS SELECT name FROM main.users",
    "CREATE VIEW cte_audit AS WITH audit AS (SELECT 1 AS n) SELECT n FROM audit",

    "CREATE TRIGGER users_touch AFTER INSERT ON users BEGIN UPDATE users SET email = email WHERE id = NEW.id; END",
    "CREATE TRIGGER users_audit AFTER INSERT ON users BEGIN INSERT INTO audit(msg) VALUES('user'); END",
    "CREATE TRIGGER audit_guard AFTER INSERT ON audit BEGIN UPDATE users SET name = name; END",
    "CREATE TRIGGER on_view INSTEAD OF INSERT ON user_names BEGIN INSERT INTO users(name) VALUES(NEW.name); END",

    "INSERT INTO users(name, email) VALUES('alice', 'A@x.com'), ('bob', 'B@x.com'), ('carol', 'C@x.com')",
    "INSERT INTO orders(user_id, total) VALUES(1, 10.5), (2, 20.5)",
    "INSERT INTO prefs VALUES(1, 'theme', 'dark'), (2, 'theme', 'light')",
    # Leave the counters ahead of the surviving rows.
    "DELETE FROM users WHERE id = 3",
    "DELETE FROM orders WHERE id = 2",
    # audit picked up rows from users_audit; normalise them away so the
    # expectations do not depend on trigger firing order.
    "DELETE FROM audit",
    "INSERT INTO audit(id, msg) VALUES(1, 'created'), (2, 'checked')",

    # Sprinkled in so that both forks stand in most of the earnable pairs and
    # not in two fixtures of their own: one object written in SQL a
    # hand-written reader trips over, one object that stopped working long
    # before anyone thought about backups.
    "CREATE TABLE legacy (id INTEGER PRIMARY KEY)",
    "CREATE VIEW users_brackets AS SELECT name FROM [users]",
    "CREATE VIEW legacy_view AS SELECT id FROM legacy",
    "DROP TABLE legacy",
]

F2_CHAIN = [
    "CREATE TABLE a (id INTEGER PRIMARY KEY, w TEXT)",
    "CREATE TABLE b (id INTEGER PRIMARY KEY, z TEXT)",
    "CREATE VIEW v1 AS SELECT id, w FROM a",
    "CREATE VIEW v2 AS SELECT id, w FROM v1",
    "CREATE VIEW v3 AS SELECT v2.id, v2.w FROM v2 JOIN v1 ON v1.id = v2.id",
    "CREATE VIEW vb AS SELECT v1.w, b.z FROM v1 JOIN b ON b.id = v1.id",
    "CREATE TRIGGER t_on_v3 INSTEAD OF INSERT ON v3 BEGIN INSERT INTO a(w) VALUES(NEW.w); END",
    "CREATE VIEW v_cte2 AS WITH outer_cte AS (WITH b AS (SELECT 1 AS z) SELECT z FROM b) SELECT z FROM outer_cte",
    "INSERT INTO a VALUES(1, 'aa'), (2, 'ab')",
    "INSERT INTO b VALUES(1, 'bb')",

    "CREATE TABLE b_legacy (id INTEGER PRIMARY KEY)",
    "CREATE VIEW v_brackets AS SELECT id FROM [a]",
    "CREATE VIEW v_gone AS SELECT id FROM b_legacy",
    "DROP TABLE b_legacy",
]

F3_SEQ = [
    "CREATE TABLE alpha (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)",
    "CREATE TABLE zebra (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)",
    "CREATE TABLE plain (id INTEGER PRIMARY KEY, v TEXT)",
    "INSERT INTO alpha(v) VALUES('a1'), ('a2'), ('a3')",
    "INSERT INTO zebra(v) VALUES('z1'), ('z2')",
    "INSERT INTO plain VALUES(1, 'p1')",
    "DELETE FROM alpha WHERE id > 1",
    "DELETE FROM zebra WHERE id > 1",
]

F5_SHAPES = [
    "CREATE TABLE keep (id INTEGER PRIMARY KEY, name TEXT)",
    "CREATE TABLE other (id INTEGER PRIMARY KEY, w TEXT)",
    "CREATE VIEW kv AS SELECT id, name FROM keep",

    "CREATE VIEW v_union AS SELECT id FROM keep UNION ALL SELECT id FROM other",
    "CREATE VIEW v_union_ok AS SELECT id FROM keep UNION ALL SELECT id FROM keep",
    "CREATE VIEW v_in AS SELECT id FROM keep WHERE id IN (SELECT id FROM other)",
    "CREATE VIEW v_exists AS SELECT id FROM keep WHERE EXISTS (SELECT 1 FROM other)",
    "CREATE VIEW v_paren AS SELECT id FROM (SELECT id FROM other)",
    "CREATE VIEW v_paren_ok AS SELECT id FROM (SELECT id FROM keep)",
    "CREATE VIEW v_win AS SELECT id, row_number() OVER (ORDER BY id) AS rn FROM keep",
    "CREATE VIEW v_rec AS WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c WHERE n < 3) SELECT n FROM c",
    "CREATE VIEW v_rec_other AS WITH RECURSIVE c(n) AS (SELECT id FROM other UNION ALL SELECT n+1 FROM c WHERE n < 3) SELECT n FROM c",
    "CREATE VIEW v_cols (x) AS SELECT id FROM keep",
    'CREATE VIEW v_qualified AS SELECT k.id FROM main."keep" AS k',
    "CREATE VIEW v_cte_shadow AS WITH keep AS (SELECT 1 AS id) SELECT id FROM keep",
    "CREATE VIEW v_cte_real AS WITH c AS (SELECT id FROM other) SELECT id FROM c",
    "CREATE VIEW v_scalar AS SELECT id, (SELECT max(id) FROM other) AS m FROM keep",
    "CREATE VIEW v_scalar_ok AS SELECT id, (SELECT max(id) FROM keep) AS m FROM keep",
    "CREATE VIEW v_tvf AS SELECT j.value AS n FROM json_each('[1,2,3]') AS j",
    "CREATE VIEW v_tvf_keep AS SELECT k.id, j.value AS n FROM keep k, json_each('[1]') AS j",
    "CREATE VIEW v_comma AS SELECT keep.id FROM keep, other WHERE keep.id = other.id",
    "CREATE VIEW v_natural AS SELECT id FROM keep NATURAL JOIN other",

    "CREATE INDEX idx_collate ON keep(name COLLATE NOCASE)",
    "CREATE INDEX idx_partial ON keep(id) WHERE id > 0",
    "CREATE INDEX idx_other ON other(w)",

    "INSERT INTO keep VALUES(1, 'a'), (2, 'b')",
    "INSERT INTO other VALUES(1, 'x')",

    "CREATE TRIGGER tr_when AFTER INSERT ON keep WHEN (SELECT count(*) FROM other) > 0 BEGIN UPDATE keep SET name = name; END",
    "CREATE TRIGGER tr_when_ok BEFORE INSERT ON keep WHEN NEW.id < 0 BEGIN SELECT RAISE(ABORT, 'negative'); END",
    "CREATE TRIGGER tr_insert_select AFTER INSERT ON keep BEGIN INSERT OR IGNORE INTO other(id) SELECT id FROM keep; END",
    "CREATE TRIGGER tr_delete_other AFTER DELETE ON keep BEGIN DELETE FROM other WHERE id = OLD.id; END",
    "CREATE TRIGGER tr_update_other AFTER UPDATE ON keep BEGIN UPDATE other SET w = w; END",
    "CREATE TRIGGER tr_upsert AFTER INSERT ON keep BEGIN INSERT INTO other(id) VALUES(NEW.id) ON CONFLICT(id) DO UPDATE SET w = 'x'; END",
    "CREATE TRIGGER tr_self AFTER UPDATE ON keep BEGIN UPDATE keep SET name = name WHERE id = NEW.id; END",
    "CREATE TRIGGER tr_instead_upd INSTEAD OF UPDATE ON kv BEGIN UPDATE keep SET name = NEW.name WHERE id = NEW.id; END",
    "CREATE TRIGGER tr_instead_del INSTEAD OF DELETE ON kv BEGIN DELETE FROM other; END",
    "CREATE TRIGGER tr_cte_body AFTER INSERT ON keep BEGIN INSERT OR IGNORE INTO other(id) SELECT id FROM (SELECT id FROM keep); END",

    "CREATE VIEW v_in_with AS SELECT id FROM keep WHERE id IN (WITH c(x) AS (SELECT id FROM keep) SELECT x FROM c)",
    "CREATE VIEW v_badcol AS SELECT nosuch FROM keep",
]

F7_PARSER = [
    "CREATE TABLE keep (id INTEGER PRIMARY KEY, name TEXT)",
    "CREATE VIEW p01 AS SELECT * FROM keep ORDER BY id LIMIT 5 OFFSET 1",
    "CREATE VIEW p02 AS SELECT id, CASE WHEN id > 1 THEN 'a' ELSE 'b' END AS c FROM keep",
    "CREATE VIEW p03 AS SELECT group_concat(name, ',') AS g FROM keep GROUP BY id HAVING count(*) > 0",
    "CREATE VIEW p04 AS SELECT CAST(id AS TEXT) AS s FROM keep",
    "CREATE VIEW p05 AS SELECT id FROM keep WHERE name GLOB 'a*' OR name LIKE 'b%'",
    "CREATE VIEW p06 AS SELECT id FROM keep WHERE id BETWEEN 1 AND 2",
    "CREATE VIEW p07 AS SELECT name COLLATE NOCASE AS n FROM keep",
    "CREATE VIEW p08 AS SELECT json_extract('{\"a\":1}', '$.a') AS j FROM keep",
    "CREATE VIEW p09 AS SELECT id, lag(id) OVER w AS l FROM keep WINDOW w AS (ORDER BY id)",
    "CREATE VIEW p10 AS SELECT DISTINCT name FROM keep",
    "CREATE VIEW p11 AS SELECT k1.id FROM keep AS k1 LEFT OUTER JOIN keep AS k2 ON k1.id = k2.id",
    "CREATE VIEW p12 AS SELECT id FROM keep EXCEPT SELECT id FROM keep WHERE id < 0",
    "CREATE VIEW p13 AS SELECT id FROM keep INTERSECT SELECT id FROM keep",
    "CREATE VIEW p14 AS SELECT id FROM keep WHERE id NOT IN (SELECT id FROM keep WHERE id < 0)",
    "CREATE VIEW p15 AS SELECT (SELECT count(*) FROM keep) AS n",
    "CREATE INDEX p16 ON keep(name DESC, id ASC)",
    "CREATE UNIQUE INDEX p17 ON keep(name) WHERE id > 0",
    "CREATE TRIGGER p18 BEFORE UPDATE OF name ON keep FOR EACH ROW BEGIN SELECT 1; END",
    "CREATE TRIGGER p19 AFTER INSERT ON keep BEGIN UPDATE OR IGNORE keep SET name = NEW.name WHERE id = NEW.id; END",
    "CREATE TRIGGER p20 AFTER DELETE ON keep BEGIN DELETE FROM keep WHERE id = OLD.id + 100000; END",
    "INSERT INTO keep VALUES(1, 'a'), (2, 'b')",
    "CREATE VIEW p21 AS SELECT k1.id FROM keep k1 RIGHT JOIN keep k2 ON k1.id = k2.id",
    "CREATE VIEW p22 AS SELECT nosuch FROM keep",
]

# F8 is the database nobody writes on purpose and everybody ends up with: legal
# SQLite spelled in ways a hand-written reader does not expect, next to objects
# that were already broken when the backup was taken.  Every object whose name
# starts with a_ or b_ needs nothing outside keep/keep2; the c_ ones do.
F8_WILD = [
    "CREATE TABLE keep (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)",
    "CREATE TABLE keep2 (id INTEGER PRIMARY KEY, v TEXT)",
    "CREATE TABLE other (id INTEGER PRIMARY KEY, w TEXT)",
    "CREATE TABLE gone (id INTEGER PRIMARY KEY)",
    "INSERT INTO keep(v) VALUES('a'), ('b'), ('c')",
    "INSERT INTO keep2 VALUES(1, 'x')",
    "INSERT INTO other VALUES(1, 'y')",

    "CREATE VIEW a_brackets AS SELECT id FROM [keep]",
    "CREATE VIEW a_over_brackets AS SELECT id FROM a_brackets",
    "CREATE VIEW a_from_with AS SELECT x AS id FROM (WITH c(x) AS (SELECT id FROM keep) SELECT x FROM c)",
    "CREATE VIEW a_in_with AS SELECT id FROM keep WHERE id IN (WITH c(x) AS (SELECT id FROM keep2) SELECT x FROM c)",
    "CREATE VIEW a_scalar_with AS SELECT id, (WITH c(x) AS (SELECT 1) SELECT x FROM c) AS m FROM keep",
    "CREATE VIEW a_in_values AS SELECT id FROM keep WHERE id IN (VALUES(1),(2))",
    "CREATE VIEW a_right AS SELECT k.id FROM keep k RIGHT JOIN keep2 k2 ON k.id = k2.id",
    "CREATE VIEW a_full AS SELECT k.id FROM keep k FULL OUTER JOIN keep2 k2 ON k.id = k2.id",
    "CREATE VIEW a_isdistinct AS SELECT id FROM keep WHERE v IS DISTINCT FROM 'x'",
    "CREATE VIEW a_underscores AS SELECT id FROM keep WHERE id <> 1_000",
    "CREATE VIEW a_agg_order AS SELECT group_concat(v, ',' ORDER BY id) AS id FROM keep",
    'CREATE VIEW a_cast_quoted AS SELECT CAST(id AS "TEXT") AS id FROM keep',
    "CREATE INDEX a_idx_brackets ON [keep](v)",
    "CREATE TRIGGER a_tr_with_ins AFTER INSERT ON keep BEGIN INSERT OR IGNORE INTO keep2(id, v) WITH c(x) AS (SELECT 1) SELECT x, 'z' FROM c; END",
    "CREATE TRIGGER a_tr_brackets AFTER UPDATE ON [keep] BEGIN UPDATE keep2 SET v = v; END",

    "CREATE VIEW b_dangling AS SELECT id FROM gone",
    "CREATE TRIGGER b_new_in_delete AFTER DELETE ON keep BEGIN UPDATE keep SET v = NEW.v; END",
    "CREATE VIEW b_badcol AS SELECT nosuch FROM keep",

    "CREATE VIEW c_ok AS SELECT id FROM keep",
    "CREATE VIEW c_leak AS SELECT id FROM keep WHERE id IN (SELECT id FROM other)",
    "CREATE TRIGGER c_leak_tr AFTER INSERT ON keep BEGIN INSERT INTO other(id) VALUES(NEW.id); END",
    "CREATE INDEX c_idx_other ON other(w)",
    "DROP TABLE gone",
]

# F9 is the same question with the exotic syntax taken away: nothing here is
# hard to read, and the answer still depends on running both databases.
F9_BROKEN = [
    "CREATE TABLE keep (id INTEGER PRIMARY KEY, v TEXT)",
    "CREATE TABLE other (id INTEGER PRIMARY KEY, w TEXT)",
    "CREATE TABLE gone (id INTEGER PRIMARY KEY)",
    "INSERT INTO keep VALUES(1, 'a'), (2, 'b')",
    "INSERT INTO other VALUES(1, 'y')",

    "CREATE VIEW d_dangling AS SELECT id FROM gone",
    "CREATE VIEW d_over_dangling AS SELECT id FROM d_dangling",
    "CREATE VIEW d_badcol AS SELECT nosuch FROM keep",
    "CREATE TRIGGER d_new_in_delete AFTER DELETE ON keep BEGIN UPDATE keep SET v = NEW.v; END",
    "CREATE VIEW d_ok AS SELECT id FROM keep",
    "CREATE VIEW d_leak AS SELECT id FROM other",
    "CREATE INDEX d_idx_other ON other(w)",
    "CREATE INDEX d_idx_keep ON keep(v)",
    "DROP TABLE gone",
]

# F4 exists only to pin the untouched full-dump path, warts and all: it carries
# a virtual table (which the whole-database dump has never round-tripped) and
# sqlite_stat1.  It is never restored and never asked for by subset.
F4_REGRESS = F1_SHOP + [
    "CREATE VIRTUAL TABLE ft USING fts5(body)",
    "INSERT INTO ft(body) VALUES('hello world')",
    "ANALYZE",
]

F6_ODD = [
    "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)",
    "CREATE TABLE audit (id INTEGER PRIMARY KEY, msg TEXT)",
    "CREATE VIEW user_names AS SELECT name FROM users",
    "CREATE TRIGGER on_view INSTEAD OF INSERT ON user_names BEGIN INSERT INTO users(name) VALUES(NEW.name); END",
    "CREATE INDEX idx_audit_msg ON audit(msg)",
    "INSERT INTO users(name) VALUES('alice')",
]

# F10: "the same errors where the original had errors" -- every view below is
# broken in the ORIGINAL, each in a different shape, and NONE of the shapes is
# "no such table".  Take `other` out of the subset and each would fail with a
# different message ("no such table: main.other"), so the ticket's rule --
# "whatever cannot come out that way does not come at all" -- keeps them out of
# subset {keep}; with both tables kept, all of them ride.  The corpus so far
# only ever posed this decision with "no such column" (v_badcol/p22/b_badcol):
# a reader matching that one message would have passed L18-L20 while still
# repairing every other broken database it is handed.
F10_ERRSHAPES = [
    "CREATE TABLE long_gone (z INTEGER)",
    "CREATE TABLE keep (id INTEGER PRIMARY KEY, a TEXT)",
    "CREATE TABLE other (id INTEGER PRIMARY KEY, b TEXT)",
    "INSERT INTO keep(a) VALUES('x')",
    "INSERT INTO keep(a) VALUES('y')",
    "INSERT INTO other(b) VALUES('p')",
    # broken: the two arms of the UNION differ in arity
    "CREATE VIEW v_arity AS SELECT a FROM keep UNION SELECT id, b FROM other",
    # broken: there is no such function
    "CREATE VIEW v_func AS SELECT nosuchfn(b) FROM other",
    # broken: the column name is ambiguous across the join
    "CREATE VIEW v_ambig AS SELECT id FROM keep JOIN other",
    # broken: an aggregate in WHERE
    "CREATE VIEW v_agg AS SELECT b FROM other WHERE count(*) > 1",
    # broken: more columns named than the SELECT provides
    "CREATE VIEW v_ncol (x, y) AS SELECT b FROM other",
    # broken the SAME way on both sides once long_gone is dropped: must ride
    "CREATE VIEW v_dangling AS SELECT * FROM long_gone",
    "CREATE VIEW v_ok AS SELECT a FROM keep",
    "DROP TABLE long_gone",
]

# F11: the ticket's own list of what the caller may send -- "a repeated name,
# an empty one, a name that is not a table, ... a name with punctuation in it"
# -- with a broken view's ride/stay decision hanging on each answer.  L10 asks
# only that such a request is answered by a file that loads or by an error;
# the ticket asks more of the ones that DO load: "a request the endpoint
# accepts today it still accepts", and the file it hands back is still held to
# the same single sentence as any other subset backup.
F11_REQUESTS = [
    "CREATE TABLE keep (id INTEGER PRIMARY KEY, a TEXT)",
    'CREATE TABLE "odd;name" (id INTEGER PRIMARY KEY, c TEXT)',
    "CREATE TABLE other (id INTEGER PRIMARY KEY, b TEXT)",
    "INSERT INTO keep(a) VALUES('x')",
    "INSERT INTO \"odd;name\"(c) VALUES('s')",
    "INSERT INTO other(b) VALUES('p')",
    "CREATE VIEW v_keep AS SELECT a FROM keep",
    "CREATE VIEW v_badcol AS SELECT nosuch FROM other",
    'CREATE VIEW v_punct AS SELECT c FROM "odd;name"',
]

# F12: "the same thing next" beside the ride/stay decision: the counter of the
# kept table carries, no counter row of the dropped table leaks, and the
# broken view is not "repaired" along the way by a dump that got the counters
# right.
F12_NEXT = [
    "CREATE TABLE keep (id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT)",
    "CREATE TABLE other (id INTEGER PRIMARY KEY AUTOINCREMENT, b TEXT)",
    "INSERT INTO keep(a) VALUES('x')",
    "INSERT INTO keep(a) VALUES('y')",
    "INSERT INTO keep(a) VALUES('z')",
    "DELETE FROM keep WHERE id > 1",
    "INSERT INTO other(b) VALUES('p')",
    "INSERT INTO other(b) VALUES('q')",
    "DELETE FROM other",
    "CREATE VIEW v_badcol AS SELECT nosuch FROM other",
    "CREATE VIEW v_ok AS SELECT a FROM keep",
]

FIXTURES = {
    "F1_shop": F1_SHOP,
    "F2_chain": F2_CHAIN,
    "F3_seq": F3_SEQ,
    "F5_shapes": F5_SHAPES,
    "F7_parser": F7_PARSER,
    "F8_wild": F8_WILD,
    "F9_broken": F9_BROKEN,
    "F4_regress": F4_REGRESS,
    "F6_odd": F6_ODD,
    "F10_errshapes": F10_ERRSHAPES,
    "F11_requests": F11_REQUESTS,
    "F12_next": F12_NEXT,
}

# Fixtures whose whole-database dump is frozen byte for byte (criterion 2).
FULL_DUMP_FIXTURES = ["F1_shop", "F2_chain", "F3_seq", "F5_shapes", "F7_parser",
                      "F8_wild", "F9_broken", "F4_regress", "F6_odd"]

# ─── graded pairs (fixture, subset) ────────────────────────────────────────
# "objects" is the hand answer where SPEC 3.3 states one; None means the
# experiment in tools/build_corpus.py is the only author of the answer.

PAIRS = [
    ("F1_shop", ["users"], [
        "idx_users_named", "idx_users_email_lower",
        "user_names", "user_names_upper", "quoted_users", "main_users", "cte_audit",
        "users_touch", "on_view", "users_brackets", "legacy_view",
    ]),
    ("F1_shop", ["users", "orders"], [
        "idx_users_named", "idx_users_email_lower",
        "user_names", "user_names_upper", "user_orders", "quoted_users", "main_users",
        "cte_audit", "users_touch", "on_view", "users_brackets", "legacy_view",
    ]),
    ("F1_shop", ["orders"], ["cte_audit", "legacy_view"]),
    ("F1_shop", ["prefs"], ["cte_audit", "legacy_view"]),
    ("F1_shop", ["users", "orders", "audit", "prefs"], [
        "idx_users_named", "idx_users_email_lower", "idx_audit_msg",
        "user_names", "user_names_upper", "user_orders", "audit_view", "user_audit",
        "quoted_users", "main_users", "cte_audit",
        "users_touch", "users_audit", "audit_guard", "on_view",
        "users_brackets", "legacy_view",
    ]),
    ("F1_shop", ["nosuch"], ["cte_audit", "legacy_view"]),

    ("F2_chain", ["a"], ["v1", "v2", "v3", "t_on_v3", "v_cte2", "v_brackets", "v_gone"]),
    ("F2_chain", ["a", "b"], ["v1", "v2", "v3", "vb", "t_on_v3", "v_cte2",
                              "v_brackets", "v_gone"]),
    ("F2_chain", ["b"], ["v_cte2", "v_gone"]),

    ("F3_seq", ["zebra"], []),
    ("F3_seq", ["alpha"], []),
    ("F3_seq", ["plain"], []),
    ("F3_seq", ["alpha", "zebra"], []),
    ("F3_seq", ["plain", "zebra"], []),

    ("F5_shapes", ["keep"], None),
    ("F5_shapes", ["other"], None),
    ("F5_shapes", ["keep", "other"], None),

    ("F7_parser", ["keep"], None),
    ("F7_parser", ["nosuch"], None),

    # b_badcol names a column of keep: with keep left out the copy says "no
    # such table" where the original says "no such column", which is not the
    # same answer, so it cannot come along.  a_over_brackets is the closure
    # running through a form the shipped reader cannot read.
    ("F8_wild", ["keep", "keep2"], [
        "a_brackets", "a_over_brackets", "a_from_with", "a_in_with", "a_scalar_with",
        "a_in_values", "a_right", "a_full", "a_isdistinct", "a_underscores",
        "a_agg_order", "a_cast_quoted", "a_idx_brackets", "a_tr_with_ins",
        "a_tr_brackets", "b_dangling", "b_new_in_delete", "b_badcol", "c_ok",
    ]),
    ("F8_wild", ["keep"], [
        "a_brackets", "a_over_brackets", "a_from_with", "a_scalar_with",
        "a_in_values", "a_isdistinct", "a_underscores", "a_agg_order",
        "a_cast_quoted", "a_idx_brackets", "b_dangling", "b_new_in_delete",
        "b_badcol", "c_ok",
    ]),
    ("F8_wild", ["keep2"], ["b_dangling"]),

    ("F9_broken", ["keep"], ["d_dangling", "d_over_dangling", "d_badcol",
                             "d_new_in_delete", "d_ok", "d_idx_keep"]),
    ("F9_broken", ["other"], ["d_dangling", "d_over_dangling", "d_leak", "d_idx_other"]),
    ("F9_broken", ["keep", "other"], ["d_dangling", "d_over_dangling", "d_badcol",
                                      "d_new_in_delete", "d_ok", "d_leak",
                                      "d_idx_other", "d_idx_keep"]),

    # F10: five broken-in-the-original shapes, none of them "no such column".
    # With only keep, every view naming `other` would answer a different error
    # and so stays out; with both tables, every one of them rides.
    ("F10_errshapes", ["keep"], ["v_dangling", "v_ok"]),
    ("F10_errshapes", ["keep", "other"], ["v_arity", "v_func", "v_ambig",
                                          "v_agg", "v_ncol", "v_dangling",
                                          "v_ok"]),

    # F11: the ticket's list of caller inputs, each carrying the same decision.
    # The effective subset is {keep} for the first three requests (the extra
    # name adds no table), {keep, odd;name} for the punctuated one.
    ("F11_requests", ["keep", "keep"], ["v_keep"]),
    ("F11_requests", ["keep", ""], ["v_keep"]),
    ("F11_requests", ["keep", "v_keep"], ["v_keep"]),
    ("F11_requests", ["keep", "odd;name"], ["v_keep", "v_punct"]),
    ("F11_requests", ["keep", "other"], ["v_keep", "v_badcol"]),

    # F12: counters beside the ride/stay decision.
    ("F12_next", ["keep"], ["v_ok"]),
    ("F12_next", ["keep", "other"], ["v_badcol", "v_ok"]),
]

# Inputs no caller is expected to send but which the HTTP surface passes
# straight through.  The ticket's first requirement is unconditional: what
# comes back has to load.  Nothing else is asserted about these.
ODD_SUBSETS = [
    [""],
    ["users", "users"],
    ["sqlite_sequence"],
    ["sqlite_master"],
    ["user_names"],
    ["users", "nosuch"],
    ["users;DROP TABLE audit"],
]

# ─── behaviour legs (criterion 5) ──────────────────────────────────────────
# Each leg names the minimal case that exercises it.  "present"/"absent" are
# object names in the restored database of that pair, "same_error" asks the
# restored database a question and compares its answer with the original's;
# every leg also inherits the pair's behavioural checks (the restore must be
# clean), so a leg cannot be bought by a dump that does not load.

LEGS = [
    {
        "id": "L1",
        "what": "view depends on view depends on view (transitive closure, depth 3)",
        "cases": [
            {"fixture": "F2_chain", "subset": ["a"], "present": ["v1", "v2", "v3"]},
            {"fixture": "F1_shop", "subset": ["users"], "present": ["user_names", "user_names_upper"]},
        ],
    },
    {
        "id": "L2",
        "what": "INSTEAD OF trigger hanging on a view that is itself kept",
        "cases": [
            {"fixture": "F1_shop", "subset": ["users"], "present": ["on_view"]},
            {"fixture": "F2_chain", "subset": ["a"], "present": ["t_on_v3"]},
            {"fixture": "F5_shapes", "subset": ["keep"], "present": ["tr_instead_upd"],
             "absent": ["tr_instead_del"]},
        ],
    },
    {
        "id": "L3",
        "what": "a CTE shadows the name of a real table outside the subset",
        "cases": [
            {"fixture": "F1_shop", "subset": ["users"], "present": ["cte_audit"]},
            {"fixture": "F2_chain", "subset": ["a"], "present": ["v_cte2"]},
            {"fixture": "F5_shapes", "subset": ["keep"], "present": ["v_cte_shadow"],
             "absent": ["v_cte_real"]},
        ],
    },
    {
        "id": "L4",
        "what": "quoted and schema-qualified references to a kept table",
        "cases": [
            {"fixture": "F1_shop", "subset": ["users"], "present": ["quoted_users", "main_users"]},
            {"fixture": "F5_shapes", "subset": ["keep"], "present": ["v_qualified"]},
        ],
    },
    {
        "id": "L5",
        "what": "reference that lives inside a subquery used as an expression",
        "cases": [
            {"fixture": "F1_shop", "subset": ["users"], "absent": ["user_audit"]},
            {"fixture": "F5_shapes", "subset": ["keep"],
             "absent": ["v_scalar", "v_in", "v_exists"], "present": ["v_scalar_ok"]},
        ],
    },
    {
        "id": "L6",
        "what": "the table a trigger body writes to, not the one it hangs on",
        "cases": [
            {"fixture": "F1_shop", "subset": ["users"], "absent": ["users_audit"],
             "present": ["users_touch"]},
            {"fixture": "F5_shapes", "subset": ["keep"],
             "absent": ["tr_insert_select", "tr_delete_other", "tr_update_other",
                        "tr_upsert", "tr_cte_body", "tr_when"],
             "present": ["tr_self", "tr_when_ok"]},
        ],
    },
    {
        "id": "L7",
        "what": "partial index, expression index and collation index on a kept table",
        "cases": [
            {"fixture": "F1_shop", "subset": ["users"],
             "present": ["idx_users_named", "idx_users_email_lower"]},
            {"fixture": "F5_shapes", "subset": ["keep"],
             "present": ["idx_collate", "idx_partial"], "absent": ["idx_other"]},
            {"fixture": "F7_parser", "subset": ["keep"], "present": ["p16", "p17"]},
        ],
    },
    {
        "id": "L8",
        "what": "objects replay in an order the restore can follow",
        "cases": [
            {"fixture": "F2_chain", "subset": ["a"], "order": ["v1", "v2", "v3", "t_on_v3"]},
            {"fixture": "F1_shop", "subset": ["users"], "order": ["user_names", "user_names_upper"]},
        ],
    },
    {
        "id": "L9",
        "what": "counters carry over with no row belonging to a table outside the subset",
        "cases": [
            {"fixture": "F3_seq", "subset": ["alpha", "zebra"], "seq": {"alpha": 3, "zebra": 2}},
            {"fixture": "F3_seq", "subset": ["plain"], "seq": {}},
            {"fixture": "F3_seq", "subset": ["zebra"], "seq": {"zebra": 2}},
            {"fixture": "F1_shop", "subset": ["users"], "seq": {"users": 3}},
        ],
    },
    {
        # Kept out of the blocker on purpose: an odd request is worth one leg,
        # not a cap on the whole reward.  The ticket says tables= stays a
        # supported request and that what must never come back is a file that
        # will not restore -- so a clear error on one of SQLite's own names
        # counts here exactly as much as a file that loads.  What is punished
        # is the third answer: a file handed over that does not restore.
        "id": "L10",
        "what": "a tables= request the HTTP surface passes through is answered, "
                "by a file that loads or by an error, never by a broken file",
        "odd": True,
        "cases": [],
    },
    {
        "id": "L11",
        "what": "identifiers written in [brackets] -- in FROM, as an index target, "
                "as the table a trigger hangs on",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep", "keep2"],
             "present": ["a_brackets", "a_over_brackets", "a_idx_brackets",
                         "a_tr_brackets"]},
            {"fixture": "F1_shop", "subset": ["users"], "present": ["users_brackets"]},
            {"fixture": "F2_chain", "subset": ["a"], "present": ["v_brackets"]},
        ],
    },
    {
        "id": "L12",
        "what": "WITH where it is not expected: a FROM subquery, the right of IN, "
                "a scalar subquery, the head of an INSERT in a trigger body",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep", "keep2"],
             "present": ["a_from_with", "a_in_with", "a_scalar_with", "a_tr_with_ins"]},
            {"fixture": "F5_shapes", "subset": ["keep"], "present": ["v_in_with"]},
        ],
    },
    {
        "id": "L13",
        "what": "syntax SQLite has taken since 3.39: RIGHT and FULL OUTER JOIN, "
                "IS DISTINCT FROM, IN (VALUES ...), 1_000, ORDER BY inside an "
                "aggregate, a quoted type name in CAST",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep", "keep2"],
             "present": ["a_in_values", "a_right", "a_full", "a_isdistinct",
                         "a_underscores", "a_agg_order", "a_cast_quoted"]},
            {"fixture": "F7_parser", "subset": ["keep"], "present": ["p21"]},
        ],
    },
    {
        # The other side of the fork, four shapes of it.  Everything named in
        # L14-L17 fails in the ORIGINAL too, so a restored database that
        # answers differently -- by not having the object at all -- is not the
        # database that was backed up.  "same_error" asks the restored database
        # the question and compares its answer with the original's; the
        # "absent" case in L15 is the other direction, where the original's
        # error would NOT have been the same one.
        "id": "L14",
        "what": "a view whose table was dropped under it comes back, and still "
                "fails the way it failed before",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep", "keep2"],
             "present": ["b_dangling"], "same_error": ["b_dangling"]},
            {"fixture": "F9_broken", "subset": ["keep"],
             "present": ["d_dangling"], "same_error": ["d_dangling"]},
            {"fixture": "F1_shop", "subset": ["users"],
             "present": ["legacy_view"], "same_error": ["legacy_view"]},
            {"fixture": "F2_chain", "subset": ["a"], "present": ["v_gone"]},
        ],
    },
    {
        "id": "L15",
        "what": "a view naming a column that is not there comes back where the "
                "original fails the same way, and does not where it would not",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep", "keep2"],
             "present": ["b_badcol"], "same_error": ["b_badcol"]},
            {"fixture": "F9_broken", "subset": ["keep"],
             "present": ["d_badcol"], "same_error": ["d_badcol"]},
            {"fixture": "F9_broken", "subset": ["other"], "absent": ["d_badcol"]},
            {"fixture": "F5_shapes", "subset": ["keep"], "present": ["v_badcol"]},
            {"fixture": "F7_parser", "subset": ["keep"], "present": ["p22"]},
        ],
    },
    {
        "id": "L16",
        "what": "a trigger that fails on the very operation it hangs on comes "
                "back, so the table goes on refusing that operation",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep", "keep2"],
             "present": ["b_new_in_delete"]},
            {"fixture": "F9_broken", "subset": ["keep"], "present": ["d_new_in_delete"]},
        ],
    },
    {
        "id": "L17",
        "what": "the chain runs through an object that is already broken: a view "
                "over a view that does not answer",
        "cases": [
            {"fixture": "F9_broken", "subset": ["keep"],
             "present": ["d_over_dangling"], "same_error": ["d_over_dangling"]},
            {"fixture": "F9_broken", "subset": ["other"], "present": ["d_over_dangling"]},
        ],
    },
    # L18-L20 are the absent direction of L14-L17, held to the same standard
    # the present direction already gets four legs for.  "The same errors where
    # the original had errors" cuts both ways: a broken view rides only where
    # its failure survives the ride.  v_badcol / p22 / b_badcol all fail the
    # original with "no such column"; drop the table they name and the restored
    # copy would fail with "no such table" instead -- a different answer, so
    # the ticket's rule ("whatever cannot come out that way does not come at
    # all") keeps them out of exactly those subsets and nowhere else.  Each leg
    # pairs the absent case with the present case of the SAME object, so a dump
    # that throws everything away buys none of them.
    {
        "id": "L18",
        "what": "the subset decides for the broken view: v_badcol rides beside "
                "its table and stays out of a subset that dropped it, because "
                "'no such table' is not the error the original gives",
        "cases": [
            {"fixture": "F5_shapes", "subset": ["other"],
             "absent": ["v_badcol"], "present": ["v_cte_shadow"]},
            {"fixture": "F5_shapes", "subset": ["keep"], "present": ["v_badcol"]},
        ],
    },
    {
        "id": "L19",
        "what": "a subset that names no real table restores an empty database: "
                "being broken in the original is not a ticket to ride along",
        "cases": [
            {"fixture": "F7_parser", "subset": ["nosuch"], "absent": ["p22"]},
            {"fixture": "F7_parser", "subset": ["keep"], "present": ["p22"]},
        ],
    },
    {
        "id": "L20",
        "what": "two tables kept and a broken view naming a third: membership "
                "in the subset, not brokenness, decides -- next to objects "
                "that do ride broken",
        "cases": [
            {"fixture": "F8_wild", "subset": ["keep2"],
             "absent": ["b_badcol"], "present": ["b_dangling"]},
            {"fixture": "F8_wild", "subset": ["keep", "keep2"], "present": ["b_badcol"]},
        ],
    },
    # L21-L24: "the same errors where the original had errors" is about the
    # ERROR, not about the one error the corpus happened to use.  Every broken
    # object L14-L20 pose the ride/stay decision with fails as "no such
    # column" (v_badcol, d_badcol, b_badcol, p22) or "no such table"
    # (dangling); a reader that pattern-matches those two messages -- or one
    # that asks SQLite only WHETHER the view works, which is the same
    # collapse -- answers every leg above without ever comparing answers.
    # F10 poses the identical decision through four other shapes SQLite's own
    # error surface has: arity, resolution, ambiguity, and view-shape errors.
    # A correct tree passes all four with the same comparison that passes
    # L18-L20 (c1e51974's probesEqual took every one of these unseen); a tree
    # that reduced the answer to a boolean fails all four on the same line of
    # its code.  Each leg pairs the absent case with the present case of the
    # SAME view in the two-table subset, plus the in-fixture controls that DO
    # ride, so throwing everything away buys none of them.
    {
        "id": "L21",
        "what": "a view whose UNION arms differ in width fails that way in the "
                "original; 'no such table' is a different answer, so it stays "
                "out of the one-table subset and rides in the two-table one",
        "cases": [
            {"fixture": "F10_errshapes", "subset": ["keep"],
             "absent": ["v_arity"], "present": ["v_dangling", "v_ok"]},
            {"fixture": "F10_errshapes", "subset": ["keep", "other"],
             "present": ["v_arity"], "same_error": ["v_arity"]},
        ],
    },
    {
        "id": "L22",
        "what": "a view calling a function that does not exist fails that way "
                "in the original; the restored database has to give the same "
                "answer or not have the view at all",
        "cases": [
            {"fixture": "F10_errshapes", "subset": ["keep"],
             "absent": ["v_func"], "present": ["v_dangling", "v_ok"]},
            {"fixture": "F10_errshapes", "subset": ["keep", "other"],
             "present": ["v_func"], "same_error": ["v_func"]},
        ],
    },
    {
        "id": "L23",
        "what": "a view with an ambiguous column across a join fails that way "
                "in the original -- ambiguity is an answer too, and it is not "
                "'no such table'",
        "cases": [
            {"fixture": "F10_errshapes", "subset": ["keep"],
             "absent": ["v_ambig"], "present": ["v_dangling", "v_ok"]},
            {"fixture": "F10_errshapes", "subset": ["keep", "other"],
             "present": ["v_ambig"], "same_error": ["v_ambig"]},
        ],
    },
    {
        "id": "L24",
        "what": "an aggregate misused in WHERE and a view naming more columns "
                "than its SELECT yields: two more shapes of a broken original "
                "that must come back broken the same way or not at all",
        "cases": [
            {"fixture": "F10_errshapes", "subset": ["keep"],
             "absent": ["v_agg", "v_ncol"], "present": ["v_dangling", "v_ok"]},
            {"fixture": "F10_errshapes", "subset": ["keep", "other"],
             "present": ["v_agg", "v_ncol"], "same_error": ["v_agg", "v_ncol"]},
        ],
    },
    # L25-L28: the ticket names what the caller may send, in as many words --
    # "It takes whatever the caller sends -- a repeated name, an empty one, a
    # name that is not a table, one of SQLite's own, a name with punctuation
    # in it -- and a request the endpoint accepts today it still accepts."
    # L10 already asks that such a request is answered by a file that loads or
    # by an error; these four ask what the ticket asks of the ones that DO
    # load: the file is still a subset backup, held to the same one sentence,
    # ride/stay decision included.  Each request's effective subset is {keep}
    # (or {keep, odd;name}), so v_badcol -- broken in the original as "no such
    # column", differently once `other` is gone -- must stay out, while v_keep
    # (and v_punct beside its own table) must ride; the present case of
    # v_badcol itself sits in the {keep, other} pair.
    {
        "id": "L25",
        "what": "a repeated name: tables=keep,keep is the subset {keep}, and "
                "the decision for the broken view is made for that subset",
        "cases": [
            {"fixture": "F11_requests", "subset": ["keep", "keep"],
             "absent": ["v_badcol"], "present": ["v_keep"]},
            {"fixture": "F11_requests", "subset": ["keep", "other"],
             "present": ["v_badcol"]},
        ],
    },
    {
        "id": "L26",
        "what": "an empty name: tables=keep, adds no table, and the file that "
                "comes back is still the {keep} backup, not a repaired one",
        "cases": [
            {"fixture": "F11_requests", "subset": ["keep", ""],
             "absent": ["v_badcol"], "present": ["v_keep"]},
            {"fixture": "F11_requests", "subset": ["keep", "other"],
             "present": ["v_badcol"]},
        ],
    },
    {
        "id": "L27",
        "what": "a name that is not a table -- a view's own name in tables= "
                "-- names no table, and the broken view still stays out",
        "cases": [
            {"fixture": "F11_requests", "subset": ["keep", "v_keep"],
             "absent": ["v_badcol"], "present": ["v_keep"]},
            {"fixture": "F11_requests", "subset": ["keep", "other"],
             "present": ["v_badcol"]},
        ],
    },
    {
        "id": "L28",
        "what": "a name with punctuation in it: the punctuated table and its "
                "view ride, the broken view naming a dropped table does not",
        "cases": [
            {"fixture": "F11_requests", "subset": ["keep", "odd;name"],
             "absent": ["v_badcol"], "present": ["v_keep", "v_punct"]},
            {"fixture": "F11_requests", "subset": ["keep", "other"],
             "present": ["v_badcol"]},
        ],
    },
    # L29: "the same thing next" and the ride/stay decision are one file, not
    # two: the counter of the kept table carries, no counter row of the
    # dropped table leaks, and getting the counters right does not buy a
    # "repaired" view on the side.
    {
        "id": "L29",
        "what": "counters carried and the broken view still out: the next key "
                "of keep is the original's, no counter row of other leaks, "
                "and v_badcol stays out of the {keep} backup",
        "cases": [
            {"fixture": "F12_next", "subset": ["keep"],
             "absent": ["v_badcol"], "present": ["v_ok"], "seq": {"keep": 3}},
            {"fixture": "F12_next", "subset": ["keep", "other"],
             "present": ["v_badcol"], "seq": {"keep": 3, "other": 2}},
        ],
    },
]


def pair_id(fixture, subset):
    return "%s__%s" % (fixture, "+".join(subset) if subset else "ALL")


def odd_id(subset):
    return "F6_odd__odd%d" % ODD_SUBSETS.index(subset)
