# Coding Environment (HUD v6)

One environment, deployed once. Every task is a folder of uploads: the agent gets the
codebase over a sandboxed `ssh` workspace (git history vaulted), grading is diff-based
(capture the agent's diff, reset, re-apply, run hidden graders the agent never saw).

## Workflow

```bash
hud deploy                                        # once
hud sync tasks <taskset> tasks.py --yes           # per change
```

To add or change a task: add or edit a folder under `tasks/` (layout below) and re-run the sync.
Importing `tasks.py` packages every folder (the codebase at its sha, the grading pack), uploads
whatever changed as data files with `HUD_API_KEY` (the key `hud deploy` uses), and emits one
`Task` row per folder. Unchanged folders make no network call; the content-hash memo and the
built zips live in the gitignored `tasks/.cache/`. Then `hud eval tasks.py claude --task-ids <name> --runtime hud --yes`.

## A task folder

```
tasks/<name>/
  task.json          slug, description, codebase {repo_url, sha}   (packaging only; never a task arg)
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
- `coding/uploads.py` — the row models, data-file download/unpack, and the package + upload side used by `tasks.py`
- `coding/judge.py` — the tool-using LLM judge
- `coding/repo.py` — vault, snapshot, diff, reset, apply
- `tasks.py` — the Task rows `hud sync` / `hud eval` read; packages and uploads each folder at import
- `tasks/<name>/` — the four tasks so far: `fix_aggregate_listing`, `exemplar_storage_contention`, `fastify_route_concurrency`, `dump_subset_schema_object_filter`

## Tests

```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```

See the [full docs](https://docs.hud.ai) for tasks, evaluation, and scaling.
