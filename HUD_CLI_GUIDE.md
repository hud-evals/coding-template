# HUD CLI Reference

There are two CLIs you'll use with this template:

- **`imagectl4.py`** — Local-only convenience commands. A wrapper over the HUD Python API for building, validating, and running scenarios on your machine. Use this for day-to-day development and iteration.
- **`hud`** — The official HUD CLI. Use this for remote deployment, remote evaluation, and local development via `hud dev`.

---

## `imagectl4.py` — Local Development

Use `imagectl4.py` to build, validate, and run scenarios locally.

### Build, Validate, Run

```bash
# Build the image
uv run imagectl4.py my-image -b

# Validate that your task branches and grading are correct
uv run imagectl4.py my-image -v

# Run an agent against scenarios
uv run imagectl4.py my-image -r

# Combine flags — actions execute in order: build -> validate -> run -> push -> json
uv run imagectl4.py my-image -bvr
```

Edit tasks in `tasks/*.py` or grading in `grading/`, rebuild with `-b`, and re-validate/run.

### Target Specific Scenarios

Use `--ids` to target specific scenarios, or omit it to run all registered scenarios:

```bash
uv run imagectl4.py my-image -vr --ids my-task-1 my-task-2
```

### Generate Task JSON

Use `-j` to regenerate both `problem-metadata.json` and `remote_tasks.json`:

```bash
uv run imagectl4.py my-image -j
uv run imagectl4.py my-image -j --ids my-task  # specific scenarios only
```

`remote_tasks.json` is used by `hud eval` for remote evaluation.

### Full Pipeline

```bash
# Build, validate, run, push, and generate metadata in one command
uv run imagectl4.py my-image -bvrpj --ids my-task
```

---

## `hud` — Official HUD CLI

Use the `hud` CLI for local development with hot-reload, remote evaluation, and deployment.

### Local Development (`hud dev`)

```bash
# Build the Docker image
hud build .

# Start with hot-reload on tasks/grading
hud dev -w tasks -w grading --port 8765
```

### Remote Evaluation (`hud eval`)

Use `hud eval` with `remote_tasks.json` to run evaluations remotely on the HUD platform:

```bash
# Single task test
hud eval remote_tasks.json claude

# Full evaluation
hud eval remote_tasks.json claude --full

# Remote execution on HUD platform
hud eval remote_tasks.json claude --full --remote
```

### Deploy (`hud deploy`)

Deploy requires `REPO_URL`:

```bash
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo

# With runtime env vars
hud deploy . --build-arg REPO_URL=... -e API_KEY=xxx

# Private repos
hud deploy . --build-arg REPO_URL=... --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN
```

#### Secrets vs Env Vars

| Type | When | Example |
|------|------|---------|
| `--secret` | Docker build time (encrypted) | `CODING_GITHUB_TOKEN` |
| `-e` / `--env` | Container runtime | `API_KEY`, `DEBUG` |

After first deploy, subsequent `hud deploy` rebuilds the same environment (linked via `.hud/deploy.json`).
