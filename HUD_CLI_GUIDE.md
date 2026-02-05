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

## Creating a Task

Add to `tasks/basic.py`:

```python
@env.scenario("my-task")
async def my_task(hints_enabled: bool = False):
    """Task description."""
    
    setup_task(
        task_id="my_task",
        base="my_task_baseline",
        test="my_task_test",
        golden="my_task_golden",
    )
    
    prompt = make_prompt("Fix the bug in foo.py...")
    
    _ = yield prompt
    
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            base="my_task_baseline",
            test="my_task_test",
            golden="my_task_golden",
            test_files=["test_foo.py"],
        )
    ])
    
    yield grade.score
```

Then test with:
```python
# In local_test.py
task = env("my-task")
```

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
