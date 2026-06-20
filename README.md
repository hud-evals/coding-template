# Coding Environment (HUD v6)

A HUD v6 environment where an agent **fixes a bug in a Python web app**, graded by a hidden pytest
suite. The env publishes a sandboxed **`ssh` workspace** — the agent's harness brings its own bash
and file tools and drives it over SSH; the env ships no agent tools itself.

Grading uses a 3-branch design: every task has `{task}_baseline` (the agent's starting state),
`{task}_test` (hidden tests), and `{task}_golden` (the reference fix). `setup_task` checks out the
baseline; the grader applies the hidden test patch and runs `pytest` — all pass → reward 1.0. The
agent never sees the tests or the solution.

## Tasks

Four hand-picked bugs in the
[coding-template-sample](https://github.com/hud-evals/coding-template-sample) repo:

| Task | Difficulty | Bug |
|------|-----------|-----|
| `sentry-fix` | Basic | KeyError on a missing/null user profile |
| `notif-bug` | Medium | Event-type delimiter `_` vs `.` breaks routing |
| `settings-v2` | Hard | CompactDict filters falsy values during iteration |
| `webhook-bug` | Hard | Shared-list mutation corrupts channel resolution |

## Setup

```bash
uv sync
hud set HUD_API_KEY=your-key-here   # CLI auth, get one at hud.ai/project/api-keys
```

## Run

```bash
# local — clones the target repo into a per-process temp dir (macOS + Linux)
hud eval tasks.py claude --task-ids sample-json-bug -y --runtime local

# deploy once, then run hosted
hud deploy .
hud eval tasks.py claude --runtime hud --full
```

## Tests

```bash
uv run pytest tests/ -q
```

Offline tests drive the 3-branch grading (baseline fails, golden passes) with no Docker.

## Documentation

See the [full docs](https://docs.hud.ai) for tasks, evaluation, and scaling.
