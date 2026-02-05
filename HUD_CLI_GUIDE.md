# HUD CLI Usage

## First Time Setup

```bash
hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo
```

For private repos:
```bash
export CODING_GITHUB_TOKEN=github_pat_XXX
hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo \
            --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN
```

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
    
    grade = grade_task(
        base="my_task_baseline",
        test="my_task_test",
        golden="my_task_golden",
        test_files=["test_foo.py"],
    )
    
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

```bash
hud deploy
```
