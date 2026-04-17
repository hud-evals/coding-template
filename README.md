# Coding Environment

A coding environment where agents debug and fix bugs in a Python web application, graded by hidden test suites using pytest.

## Setup

```bash
uv sync
hud set HUD_API_KEY=your-key-here   # CLI auth, get one at hud.ai/project/api-keys
```

## Deploy & Run

```bash
hud deploy .                              # deploy the environment (once)
hud sync tasks <taskset-name>           # push tasks to a taskset (fast, re-run on every task change)
hud eval <taskset-name> --remote --full
```

**Iteration loop:** `hud deploy` is the slow step — run it once. After that, edit `tasks.py` and re-run `hud sync tasks` (takes seconds). Only redeploy when `env.py`, `Dockerfile.hud`, or system-level dependencies change.

See [Deploy & Go Remote](https://docs.hud.ai/building/running-at-scale) for deploy flags, secrets, and auto-deploy options.

## Tasks

9 tasks across three difficulty levels, all targeting the [coding-template-sample](https://github.com/hud-evals/coding-template-sample) repo:

| Task | Difficulty | Bug |
|------|-----------|-----|
| `sample-json-bug` | Basic | `str()` instead of `json.dumps()` |
| `sentry-fix` | Basic | KeyError on missing/null user profile |
| `settings-bug` | Basic | `if v` drops falsy values like `0` and `false` |
| `notif-bug` | Medium | Event type delimiter `_` vs `.` breaks routing |
| `order-bug` | Medium | Tax calculated before discount instead of after |
| `settings-v2` | Hard | CompactDict filters falsy values during iteration |
| `webhook-bug` | Hard | Shared list mutation corrupts channel resolution |

The `settings-bug` and `order-bug` tasks each have a `-hints` variant. Agents get a symptom-based bug description, use bash and editor tools in a sandboxed container, and are graded by applying hidden test patches and running `pytest`.

## 3-Branch Pattern

Every task uses the **3-branch pattern** — three branches in the target repo:

| Branch | Purpose |
|--------|---------|
| `{task}_baseline` | Starting state the agent sees and modifies |
| `{task}_test` | Hidden tests that grade the agent's solution |
| `{task}_golden` | Correct solution for validation |

At runtime, `setup_task()` generates git patches (`baseline->test`, `baseline->golden`) and checks out the baseline. The grader applies the test patch and runs `pytest` — if all tests pass, the agent scores 1.0.

### Build Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `REPO_URL` | `https://github.com/hud-evals/coding-template-sample` | Repository to clone |
| `FOLDER_NAME` | `project` | Destination folder in container |

For private repos:
```bash
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo \
             --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN
```

## Documentation

To learn more about tasks, evaluations, and running at scale see the [full docs](https://docs.hud.ai).
