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
hud sync tasks <taskset-name>             # push tasks to a taskset (fast, re-run on every task change)
hud eval <taskset-name> --remote --full
```

**Iteration loop:** `hud deploy` is the slow step — run it once. After that, edit `tasks.py` and re-run `hud sync tasks` (takes seconds). Only redeploy when `env.py` or the Dockerfile changes.

See [Deploy & Go Remote](https://docs.hud.ai/building/running-at-scale) for deploy flags, secrets, and auto-deploy options.

## Tasks

9 tasks across three difficulty levels:

**Basic** — JSON serialization bug, Sentry crash fix, settings merge bug

**Medium** — notification routing bug, order pricing calculation

**Hard** — CompactDict iteration bug, webhook channel mutation

The settings-bug and order-bug tasks each have a hints variant. Agents get a bug description, use bash and editor tools in a sandboxed container, and are graded by applying hidden test patches and running `pytest`.

## Documentation

To learn more about tasks, evaluations, and running at scale see the [full docs](https://docs.hud.ai).
