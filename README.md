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
  codebase/          optional: a local source tree, used when task.json sets codebase.path instead of repo_url and sha
  prompt.md          the ticket the agent reads
  gold.diff          the reference solution; validate_mode="golden" grades it instead of agent work
  llm_rubric.json    optional: rows judged by the LLM
  grading/           zipped as is -> the grading pack, staged at /hud/grader
    run_grading.sh   ONE bash function per criterion, named exactly as its id; shared setup on top, dispatcher at the bottom
    criteria.json    the rows: id, requirement, weight, blocker / gate, timeout, pristine_paths
    tests/ ...       hidden tests and helpers the functions run
    setup.sh         optional: dependency install + warm caches (root, before the agent); else auto-detection (below)
    services.sh      optional: start daemons the tests need (DynamoDB Local ...), return once they answer
```

For a private repository already on your machine, copy the source tree into `tasks/<name>/codebase/` and set `"codebase": {"path": "codebase"}`. The publisher zips that folder instead of cloning. `.git` is left out of the zip, and setup makes one baseline commit from the files.

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
`AGENT_DIFF` (the applied patch), `BASE_SHA`, `SETUP_COMMIT`.

## The image vs. the task

The image (`Dockerfile.hud`) is a thin base of installers and system libraries; the exact
runtimes and dependencies are resolved per task, at setup, from what the uploaded repo declares.

| | in the image | resolved at task setup (from the repo) |
|---|---|---|
| Go | Go 1.26.x, `GOTOOLCHAIN=auto` | `go.mod` / `go.work` `go`/`toolchain` line: `go` downloads a newer Go itself; `go mod download` |
| Node | `fnm` with 22 + 24 pre-warmed, corepack, pnpm 10 / yarn 1 fallbacks | `.nvmrc` / `.node-version` / `engines.node` → `use-node`; `packageManager` → pnpm/yarn version; lockfile → `pnpm install --frozen-lockfile` / `yarn install --frozen-lockfile` / `npm ci` (none: `npm install`) |
| Python | `uv`, CPython 3.11 + 3.12 pre-warmed (`python3` stays Debian's, for hud) | `.python-version` / `requires-python` → interpreter (downloaded if missing); `uv sync --frozen` / `uv sync` / `uv pip install -r requirements.txt` into `.venv` |
| Rust | `rustup`, no toolchain | `rust-toolchain(.toml)`, else `rustup default stable`; `cargo fetch` |
| Also | JRE + DynamoDB Local, SQLite 3.53.4, git, ripgrep, build-essential, libssl/libsqlite3/libpq/zlib/libffi -dev | — |

Without a `setup.sh` the env runs that detection (`setup_commands` in `env.py`); the chosen
versions are printed into `/hud/logs/setup.log`. A `setup.sh` replaces it entirely: call
`use-node <version>` to pin a Node the repo does not declare, then install. Every toolchain
cache (Go modules and builds, fnm, corepack, the pnpm store, uv, rustup) is filled by setup as
root and handed to the agent's uid afterwards, so the agent can add dependencies and toolchains
too; graders run as root and share them.

## Layout

- `env.py` — workspace, vault, the `swe-task` template (staging, setup, grading loop), the git-ref `coding-task` / `sdlc-task` flavors
- `coding/uploads.py` — the row models, data-file download/unpack, and the package + upload side used by `tasks.py`
- `coding/judge.py` — the tool-using LLM judge
- `coding/repo.py` — vault, snapshot, diff, reset, apply
- `tasks.py` — the Task rows `hud sync` / `hud eval` read; packages and uploads each folder at import
- `tasks/<name>/` — the two examples: `fastify_route_concurrency`, `fix_aggregate_listing`

## Tests

```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```

See the [full docs](https://docs.hud.ai) for tasks, evaluation, and scaling.
