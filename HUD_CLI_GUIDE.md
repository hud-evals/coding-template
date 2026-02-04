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
# Deploy current directory (builds remotely via CodeBuild)
hud deploy

# With build args for private repos
export CODING_GITHUB_TOKEN=github_pat_XXX
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo \
             --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN
```

## Rebuild Locally

```bash
# After Dockerfile changes
hud build .
```
