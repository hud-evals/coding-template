# Grader — dump_subset_schema_object_filter

Grading is 100% execution. No LLM judge, no source inspection, no heuristics.
Every criterion runs the tree's own dump path, loads what it produced with the
`sqlite3` binary and with the repo's own restore path, and compares the
restored database against **what the original database answers** — not against
a rule written down here.

## Layout

```
run_grading.sh          one function per criterion; the dispatcher tasks.py calls
tasks.py                GRADERS / FRACTIONAL / BLOCKER_CAP — the scoreboard
gohar/                  Go module: opens a fixture, calls db.Dump, writes the file,
                        pushes it back through the repo's own restore path
                        (and carries the criterion-2 API-shape assertions)
lib/corpus.py           the frozen fixture schemas, pairs and behaviour legs
lib/oracle.py           run-a-database helpers: restore, ask, compare answers
lib/driver.py           builds gohar against /workspace/repo and runs it
lib/gates.py            the repo's own gates (build / gofmt / vet / test)
lib/checkbase.py        plumbing every hidden check shares
tests/check_*.py        one hidden check per criterion
tools/build_corpus.py   freezes fixtures + expectations (run once, outside)
tools/record_gates.py   records the base tree's gate output (run at image build)
tools/calibrate.py      runs the whole grader over several trees, no Docker
data/                   fixtures (.sqlite), expected.json, full_dumps/, baselines
../gold-probes/         the two mandatory gold probes (differential, refusal)
```

Every `../` path in this file — the control trees (`../repo-base`,
`../repo-adv-parser`, …) and `../gold-probes/` — is relative to the factory
pilot this grader was built in, not to the deployment package. They are the
maintainer's local calibration bench (measurements in
`data/calibration-local.txt`), and they are deliberately not shipped in the
image: 9.4 GB of Go build caches and eleven full checkouts. Inside the image
the base tree is `/hud/base` and the calibration that must hold is run by the
build itself (`Dockerfile.hud`, step 8) into `data/calibration.txt`.

## v6 note (2026-09-03, swe-graders-v2 review)

The table below and the prose after it describe the v4/v5 scoreboards and
are kept as the record of how the corpus and the checks were built. Three
things changed in v6; `tasks.py` is the authority:

* the scored criteria are the ten v5 branch criteria, unchanged weights
  (sum 1.00, four blockers at 0.10/0.16/0.16/0.10);
* the flat `BLOCKER_CAP = 0.60` is replaced by the programme's uniform rule:
  `r = u / 3` when any blocking criterion fails, then `r = min(r, 0.2 u)`
  when any gate fails. No floor;
* a fourth gate, `anti_hack_gate` (`coding/axes.py`), runs on the agent's
  diff before the bash gates: no baseline test file deleted, no `func Test`
  removed from a pre-existing test file, no `t.Skip` added to one, no change
  under `go.mod`, `go.sum`, `.github/`, `.circleci/`, `appveyor.yml`,
  `Makefile*`, `.golangci*`, `.goreleaser*`, `scripts/`, `build/`.
  `tools/calibrate.py` does not run it (it needs a diff); the local sanity
  harness in `CHANGES.md` does.

`tools/calibrate.py` reads `BLOCKER_SCALE` and `GATE_SCALE` instead of
`BLOCKER_CAP`, and the Dockerfile pins them as `LIMIT blocker-scale 0.33` and
`LIMIT gate-scale 0.20`.

## Criteria (v4 record)

| # | criterion | weight | blocker | what it checks | how |
|---|---|---|---|---|---|
| 1 | `repo_gates_green` | 0% | yes | the repo's own gates after the change | `go build ./...`, `gofmt -l .`, `go vet ./...`, `go test ./db/... ./http/... ./command/... ./cmd/...` + `-run Test_SingleNodeBackup ./store/`, each minus what the untouched checkout already produced, and each finding re-run before it is charged (see below) |
| 2 | `full_path_and_api_unchanged` | 0% | yes | a dump with no `tables=` is byte for byte what it is today, warts and all; the exported dump API has not moved | sha256 against dumps frozen from the base tree at image build; the API shape by construction — `gohar` stops compiling if a signature moves |
| 3 | `subset_restores_and_rows_exact` | 0% | yes | the file arrives, loads under **both** readers with no error, the two restored databases are the same one, and each requested table holds exactly its rows | `sqlite3` (rc 0, empty stderr) + the repo's `ExecuteStringStmt`; rows compared through `quote()` |
| 4 | `restored_matches_original` | 60% | yes | **the restored database answers as the original does**: the schema objects are exactly the reference set and carried through verbatim, every view returns the same rows *or the same error*, every requested table answers the frozen write probes exactly as the original answers them | every probe is run twice — once on the original when the corpus was frozen, once on the restored database — and the two answers compared. **Scored as a verdict**: every pair right, or the criterion is 0 — the check still prints its per-pair fraction and FAIL lines as diagnostics |
| 5 | `behaviour_legs_coverage` | 40% | no | the same thing one named family at a time, L1–L29 | each leg names minimal cases (fixture × subset × `present` / `absent` / `order` / `seq` / `same_error`); score = fraction of legs whose every case is green |
| 6 | `next_write_matches_original` | 0% | yes | the restored database hands out the key the original would have handed out next, and carries no counter belonging to a table outside the subset | `sqlite_sequence` compared exactly; a real `INSERT` per counter table, rolled back |

**Criterion 1 charges nothing it did not measure twice.** The gate it runs is
the repo's own, and parts of that suite are wall-clock bound: `./store/` brings
a real Raft node up and waits ten seconds for an election,
`db/checkpoint_manager_test.go` sleeps two seconds and then asserts a
checkpoint happened,
`./http/` opens real listeners, and the tests an agent adds inherit those
helpers. One red sample of such a suite on a busy machine says something about
the machine. So a test that goes red here and is green in the baseline is
re-run **on its own** up to three times, and only a test that loses every one of
those isolated runs is reported; a `go build`, `go vet` or `gofmt` problem the
baseline does not have is likewise re-run whole before it counts. A step that
never finishes — a timeout, or the criterion's own 3000-second budget running
out — comes back as *unmeasured* and is not charged either. Nothing about what
the criterion means changes: a deterministically red test, an unformatted file
and a broken build are charged exactly as before. Measured on four probe trees
in `../reweight-v4/flakeprobe/`: `hardfail`, `gofmtbad` and `buildbad` are
charged; `suiteflaky` — red in the suite, green when run alone — is not.

Criterion 4 carries its weight as a verdict, not a fraction. The contract it
grades is the ticket's one binary sentence — "restoring it gives you what
restoring a whole-database backup would have given you, minus the tables you
did not ask for" — and that contract has no 84%: a restore either hands back
the database that was backed up or it hands back a different database, and an
operator cannot trust a backup that answers wrongly on 4 requests out of 25
any more than one that answers wrongly on all of them. What partial credit was
measured doing (five platform runs, job `1e5404aa`) is handing 0.37–0.40 of
the reward to runs whose restored databases answer wrongly — on top of the
per-family credit criterion 5 already pays them. The gradient belongs in
criterion 5, which names the same work family by family; a run that got most
of the shape right still collects there, leg by leg, and nowhere else.

**Weight and blocking are separate questions, and this scoreboard answers them
separately.** Four criteria block; only two carry weight.

*Weight* asks how much of the job a criterion is. A check every serious attempt
passes answers that with zero — weight parked there is weight that lifts every
wrong run toward the gate. Criteria 1 and 2 are green on an untouched checkout,
so they carry none. Criteria 3 and 6 carry none for the same reason measured
rather than assumed: across the calibration trees, criterion 3 is green on every
tree that produced a file at all, and criterion 6 is green on all four realistic
wrong solutions. Between them they were handing 0.20 to any run that got a file
out the door.

*Blocking* asks whether a run that fails it is shippable. All four say no. A
backup that does not load (3), a restored database that is not the one that was
backed up (4), a tree that breaks the repo's own gates (1) or moves the frozen
whole-database path or the exported API (2). Criterion 6 belongs with them:
handing out a key the database already handed out is wrong data, not an
incomplete feature.

Zero weight is not "unmeasured". A zero-weight blocker still has to be flat red
on the base tree — `calibrate.py` asserts it against `PRISTINE_GREEN`, which
names the only two criteria allowed to be green there — it still caps the run at
0.60, and the work it names is still scored: the counters are leg **L9** inside
criterion 5, so a run that forgets them loses that leg (measured: the
counter-less tree fails L9 on `F3_seq`, `{'alpha': 1, 'zebra': 1}` where the
original hands out `{'alpha': 3, 'zebra': 2}`).

Blockers carry **0.60** of the weight — at the 60% ceiling, not over it — and
on a blocker failure the reward is capped **flat**: `reward = min(earned, 0.60)`.
The ceiling does not slide down as more blockers fail. `calibrate.py` checks
both programme rules against the scoreboard itself and refuses to run if either
breaks.

Criterion 5 is deliberately not a blocker: it is the one criterion with a real
gradient, and it carries the whole slope under the cap, so a run that understood
the shape of the problem and missed one family does not collapse to zero. It is
also the likeliest miss of an otherwise strong run, and charging that miss twice
would flatten exactly the distinction the gradient exists to draw.

Criterion 5 is fractional: its check prints `GRADER_SCORE <x>` and `tasks.py`
reads the value off that line. The exit code still says whether the criterion
is fully satisfied, which is what the blocker rule uses. Criterion 4's check
prints the same line, but as a diagnostic only — the scoreboard reads its
verdict.

## Where the answers come from

Nothing is read off any implementation. For every (fixture, subset) pair the
reference object set is computed in `tools/build_corpus.py` as a greatest
fixpoint discovered **by experiment**: start with every schema object, build a
database holding only the requested tables plus those objects, and throw away
whatever **answers differently from the original** — an object that will not
create, a view that returns other rows or fails where the original succeeded
(or succeeds where the original failed), a trigger whose table stops answering
the way it answered before.

That is not the same fixpoint as "the greatest set that works", and the
difference is the point of the task. A view whose table was dropped years ago
fails in the original too: carrying it keeps the restored database the same
database, and quietly leaving it out repairs a database that was only meant to
be copied. Both directions are graded.

The result is then proved both ways — it holds, and adding back anything that
was thrown away changes an answer — and, where the corpus states a hand-written
answer, the experiment has to agree with it or the corpus is refused. That is
the mitigation for "the reference must not be a second, unreviewed
implementation of the gold". Trigger attribution is by isolation on **both**
sides, so a trigger legitimately left behind can never make its neighbour look
broken.

## Anti-vacuum

Two things stop "throw every view and trigger away, then it always loads" from
being a solution:

* pairs whose subset is the whole database, and fixtures whose every object
  needs only the requested table, are **control pairs**: the untouched tree
  already answers them, so they earn nothing and can only be lost. Criterion 4
  scores `max(0, earned − regressed) / (pairs the base gets wrong)`, which is
  exactly 0 for an untouched checkout, 0 for a change that drops everything,
  and 1 for the gold;
* the legs assert both directions. L1–L4, L7, L11–L14, L16, L17 name objects
  that **must be present**; L5, L6, one case of L15 and the L18–L29 cases name
  objects that **must be absent** — and every absent case in L18–L29 is paired
  with a present case of the same object (or the same fixture's ride-along
  controls) in the same leg, so a dump that throws everything away buys none
  of them.

## v4: nine more legs, one sentence each

L21–L24 (fixture `F10_errshapes`) hold "the same errors where the original had
errors" to SQLite's own error surface rather than to the one message the older
corpus used: a view broken by UNION arity, by a missing function, by an
ambiguous column, by a misused aggregate or a wrong column count fails the
original that way — and once its table leaves the subset it would fail another
way, so it stays out ("whatever cannot come out that way does not come at
all"), while riding — with the very same error text — where both tables are
kept. L25–L28 (fixture `F11_requests`) take the ticket's own list of caller
inputs — "a repeated name, an empty one, a name that is not a table, … a name
with punctuation in it" — and ask of each accepted request what the ticket
asks of every subset backup: the file that comes back is the backup of the
tables the request effectively names, ride/stay decision included. L29
(fixture `F12_next`) pairs "the same thing next" (counters carried, none
leaked) with that same decision in one file. A correct tree passes all nine
with the same answer-comparison that passes L18–L20; a tree that reduces the
question to "does the view work?" fails all nine on the same line of its code.

## One deliberate softening

The odd `tables=` requests the HTTP surface passes through (`?tables=`,
`?tables=sqlite_sequence`, a view's name, a name with a semicolon) are checked
as leg **L10** rather than inside a blocker, and for one of SQLite's own names
an honest error from `Dump` counts exactly as much as a file that loads. The
ticket forbids one answer only — "what it must never hand back is a file that
will not restore" — and the grader is no stricter. `gold-probes/honest_refusal.py`
proves the allowance is not a hole: a tree that refuses every `tables=` request,
or every database with views in it, is still punished, and by a sentence the
ticket states in as many words.

## Rebuilding the corpus

```bash
python3 tools/build_corpus.py --base-tree ../repo-base    # fixtures + expectations
python3 tools/record_gates.py ../repo-base                # gate baseline (do this
                                                          # in the image, at build)
```

## Calibration

```bash
python3 tools/calibrate.py --base ../repo-base \
    gold=../repo base=../repo-base noop=../repo-noop \
    fair_refuse=../repo-fair-refuse \
    adv_parser=../repo-adv-parser adv_probe=../repo-probe \
    adv_halfrel=../repo-adv-halfrel \
    adv_drop_all=../repo-adv3 adv_tbl_name=../repo-adv1 \
    adv_qtn_walk=../repo-adv2 adv_no_counters=../repo-adv4

python3 ../gold-probes/differential.py repo repo-adv-parser repo-probe
python3 ../gold-probes/honest_refusal.py
```

The control trees, and what each one is (every number below is measured, not
derived — the whole grader run over each tree):

| tree | what it does | measured |
|---|---|---|
| `repo` | the gold: asks SQLite, and compares its answers with the original's | 1.000 |
| `repo-fair-refuse` | the gold, refusing `tables=sqlite_*` with an error | 1.000 |
| `repo-adv-halfrel` | holds views to the original's answers, triggers only to working | 0.600 (capped from 0.827) |
| `repo-probe` | asks SQLite, but only whether things work | 0.344 |
| `repo-adv-parser` | reads the SQL itself — the tree this task replaced | 0.318 |
| `repo-adv4` | no counters | 0.291 |
| `repo-adv2` | a name walk | 0.212 |
| `repo-adv1` | `tbl_name` only | 0.079 |
| `repo-adv3` | drop everything | 0.000 |
| `repo-base`, `repo-noop` | untouched, and a cosmetic patch | 0.000 |

Two things the reweight cost, named rather than buried. `repo-adv3` collapses
to 0.000 — it now scores what the untouched tree scores, so one gradient on an
archetype nobody would actually write is gone. And `repo-adv4` lands on 0.291,
the same number the two pilots get: it fails six legs (L9 plus L11–L14, L17)
where they fail six others (L10 plus L11–L14, L17), and with the counters no
longer weighted separately the two are worth the same. Both trees are wrong
solutions far below the gate either way; what was bought is that the floor
under any run that merely produced a loadable file fell from 0.468 to 0.344.

Every tree is graded criterion by criterion, the untouched checkout included:
`tasks.py` would short-circuit an empty diff to 0.00 before any grader runs,
and a base that only reaches zero that way is a broken grader wearing a clean
number. `calibrate.py` asserts the invariants itself and exits non-zero if any
of them breaks — gold 1.00 with every criterion green; base and the cosmetic
patch 0.00 with the two `PRISTINE_GREEN` gates green and **every other
criterion flat red, weighted or not** (a zero-weight blocker that is already
green on an untouched tree is a blocker that blocks nothing); blockers holding
no more than 0.60 of the weight and the cap no lower than 0.60; every `adv_*`
tree short of 1.00 and capped by a failed blocker; `fair_*` scoring exactly
what the gold scores; and `adv_parser` and `adv_probe` — the two sides of the
fork — both red on criterion 4. If either of those ever goes green, the oracle
has stopped measuring the thing the task is about.

The scoreboard lives in `tasks.py` and nowhere else: `calibrate.py` reads
`GRADERS`, `FRACTIONAL`, `BLOCKER_CAP` and `PRISTINE_GREEN` straight out of it
with `ast`, so a reweight is one edit and these numbers cannot drift from the
ones the platform produces. It re-implements exactly one thing — the weighted
sum — and that matches HUD's `combine`, which normalizes by the positive-weight
sum (1.00 here) and passes zero weights through untouched.

No Docker needed. `GRADER_PYTHON`, `REPO_DIR`, `GRADER_DIR` and
`GRADER_STATE_DIR` are the only environment the grader reads.

## Image wiring (see `Dockerfile.hud.fragment`)

* **Pin Go 1.26.x.** On 1.27 `GOEXPERIMENT=jsonv2` makes `Test_Geopoly` fail in
  the `db` package on a pristine HEAD. The gate baseline absorbs it either way,
  but the pin keeps criterion 1 honest.
* CGO is required (`replace github.com/mattn/go-sqlite3 =>
  github.com/rqlite/go-sqlite3`), so the image needs a working C compiler, and
  the Go build cache must be warmed on the base checkout inside the Dockerfile.
* `.dockerignore` must cover `.calib`, `bin/`, `__pycache__` — the local
  calibration state is a Go build cache and runs to hundreds of megabytes.
* `run_grading.sh` picks `python3` first and falls back to
  `/usr/local/bin/python`; whichever the image resolves, only the standard
  library is used (`sqlite3`, `json`, `subprocess`). There is nothing to pip
  install.
