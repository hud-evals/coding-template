# Coding Environment (HUD v6)

One environment, deployed once. Every task is a folder of uploads: the agent gets the
codebase over a sandboxed `ssh` workspace (git history vaulted), grading is diff-based
(capture the agent's diff, reset, re-apply, run hidden graders the agent never saw).

## Workflow

```bash
uv sync
hud deploy                                   # once; the image has Node 22/24, Go 1.25/1.26, Python, JRE, SQLite
hud sync env                                 # once; links this dir to the platform env (writes .hud/config.json)

mkdir tasks/<name>                           # add a task: see the folder layout below
uv run tasks/pack.py <name>                  # -> tasks/<name>/dist/codebase.zip + grading.zip (local only)
# upload 4 files as data files (console, or `uv run tasks/upload.py <name> --run`):
#   dist/codebase.zip, dist/grading.zip, gold.diff, llm_rubric.json (if any)
# put the returned ids into tasks/<name>/uploads.json (placeholders are there)
hud sync tasks <taskset> tasks.py --yes      # tasks.py builds one Task row per folder from uploads.json
hud eval tasks.py claude --task-ids <name> --runtime hud --yes
```

Nothing is rebuilt or redeployed for a new task. Editing a grader means re-packing, re-uploading
the one changed file, updating its id in `uploads.json`, and syncing again.

## A task folder

```
tasks/<name>/
  task.json          slug, description, codebase {repo_url, sha}   (packaging only; never a task arg)
  uploads.json       the data-file ids of the four uploads (filled after uploading)
  dist/              pack.py output (gitignored): codebase.zip, grading.zip
  prompt.md          the ticket the agent reads
  gold.diff          the reference solution; validate_mode="golden" grades it instead of agent work
  llm_rubric.json    optional: rows judged by the LLM
  grading/           zipped as is -> the grading pack, staged at /hud/grader
    run_grading.sh   ONE bash function per criterion, named exactly as its id; shared setup on top, dispatcher at the bottom
    criteria.json    the rows: id, requirement, weight, blocker / gate, timeout, pristine_paths
    tests/ ...       hidden tests and helpers the functions run
    setup.sh         optional: toolchain + dependency install (root, before the agent); else lockfile auto-detection
    services.sh      optional: start daemons the tests need (DynamoDB Local ...), return once they answer
```

`criteria.json` and `llm_rubric.json` share one row shape: `{"id", "requirement", "weight", ...}`.
A `criteria.json` row is one deterministic grader: `bash run_grading.sh <id>` in the repo,
exit 0 passes, an optional trailing `GRADER_SCORE 0.5` line makes it fractional; hidden tests
are the normal content. `gate: true` rows carry no weight; failing one caps the reward at a
fifth. `blocker: true` rows scale the reward to a third when they fail. `pristine_paths` are
checked out from the baseline before the row runs (the repo's own tests cannot be edited
into passing). Rows run gates first, then in table order; put a tree-mutating row last.

An `llm_rubric.json` row is one LLM-judged criterion, judged on its own against the agent's
change: the judge sees a diff summary (files with +/- counts; small hand-written hunks
inlined) and reads the rest with read-only tools over a snapshot of the final tree and the
pre-change tree, up to 15 calls, then must answer. `negative: true` rows describe a mistake
and are penalties: the judge must quote the offending code or the row does not fire.
`tools: false` falls back to a one-shot judge over the summary. `guidance` is extra
reviewer context; `partial: true` allows a 0..1 score.

Every row is one `SubScore` on the platform: `name` = id, `weight` = the row's weight,
`info.statement` = the requirement text, plus the verdict detail (exit code and output
tail, or the judge's reason, evidence, tools used and files read).

The scripts see `REPO_DIR`, `GRADER_DIR` (the pack; `$GRADER_DIR/base` is the repo as the
agent received it, dependencies installed), `GRADER_STATE_DIR`, `GRADING_LOGS_DIR`,
`AGENT_DIFF` (the applied patch), `BASE_SHA`, `SETUP_COMMIT`. `use-node 22|24` and
`use-go 1.25|1.26` pick a toolchain in `setup.sh`.

## Layout

- `env.py` — workspace, vault, the `swe-task` template (staging, setup, grading loop), the git-ref `coding-task` / `sdlc-task` flavors
- `coding/uploads.py` — the row models and data-file download/unpack
- `coding/judge.py` — the tool-using LLM judge
- `coding/repo.py` — vault, snapshot, diff, reset, apply
- `tasks.py` — the Task rows `hud sync` / `hud eval` read (one per folder, ids from `uploads.json`)
- `tasks/pack.py` — build a folder's two zips; `tasks/upload.py` — optional API upload that fills `uploads.json`
- `tasks/<name>/` — the four tasks so far: `fix_aggregate_listing`, `exemplar_storage_contention`, `fastify_route_concurrency`, `dump_subset_schema_object_filter`

## Tests

```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```

See the [full docs](https://docs.hud.ai) for tasks, evaluation, and scaling.
