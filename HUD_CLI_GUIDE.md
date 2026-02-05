# HUD CLI Usage

## First Time Setup (Local)

```bash
git submodule update --init
hud build .
```

Or with URL: `hud build . --build-arg REPO_URL=https://github.com/...`

## Local Development

```bash
# Terminal 1
hud dev -w tasks -w grading --port 8765

# Terminal 2
python local_test.py
```

Edit tasks or grading code, save, re-run `local_test.py`. No rebuild needed.

## Run Agent Evaluation

```bash
# Single task test
hud eval remote_tasks.json claude

# Full evaluation
hud eval remote_tasks.json claude --full

# Remote execution on HUD platform  
hud eval remote_tasks.json claude --full --remote
```

## Deploy to HUD Platform

Deploy **requires** `REPO_URL` (submodule only works locally):

```bash
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo

# With runtime env vars
hud deploy . --build-arg REPO_URL=... -e API_KEY=xxx

# Private repos
hud deploy . --build-arg REPO_URL=... --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN
```

### Secrets vs Env Vars

| Type | When | Example |
|------|------|---------|
| `--secret` | Docker build time (encrypted) | `CODING_GITHUB_TOKEN` |
| `-e` / `--env` | Container runtime | `API_KEY`, `DEBUG` |

After first deploy, subsequent `hud deploy` rebuilds the same environment (linked via `.hud/deploy.json`).
