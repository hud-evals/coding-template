# Quick Start Guide

Get up and running with the evaluation framework in 15 minutes.

## Prerequisites

- Python 3.11+
- Git
- Your target repository with a build system

## Installation (5 minutes)

```bash
# 1. Install the framework
pip install -e .

# 2. Set environment variables
export REPO_PATH="/path/to/your/repository"
export TEST_DB_NAME="your_test_db"  # Optional, if using database
export MCP_TESTING_MODE="1"

# 3. Verify installation
python -c "from hud_controller.spec import PROBLEM_REGISTRY; print(f'Found {len(PROBLEM_REGISTRY)} problems')"
```

## Creating Your First Task (10 minutes)

### Step 1: Prepare Git Branches (3 minutes)

```bash
cd /path/to/your/repository

# Create baseline (starting point)
git checkout -b my_first_task_baseline main

# Create test branch (add failing tests)
git checkout -b my_first_task_test my_first_task_baseline
# ... add test file ...
git add . && git commit -m "Add test"

# Create golden branch (add solution)
git checkout -b my_first_task_golden my_first_task_test
# ... implement fix ...
git add . && git commit -m "Add solution"

# Push all branches
git push origin my_first_task_baseline my_first_task_test my_first_task_golden
```

### Step 2: Define the Task (5 minutes)

Create or edit `src/hud_controller/extractors/basic_tasks.py`:

```python
@problem(
    id="my_first_task",
    description="Fix the bug in module X where Y happens when Z",
    hints=[],
    difficulty="easy",
    task_type="coding",
    review_level="no-review",
    base="my_first_task_baseline",
    test="my_first_task_test",
    golden="my_first_task_golden",
)
def my_first_task(state: EnvironmentState) -> Grade:
    """Task: Fix bug in module X"""
    return Grade.from_subscores([
        AgentPatchGrader.grade(
            state=state,
            weight=1.0,
            base="my_first_task_baseline",
            test="my_first_task_test",
            golden="my_first_task_golden",
            jest_test_files=["path/to/test.test.ts"],  # Update for your test
        )
    ])
```

### Step 3: Test It (2 minutes)

```bash
# Run the grading
grade_problem my_first_task

# Check the output
# - Should show grading progress
# - Should run tests
# - Should output a score (0.0 or 1.0)
```

## Common Workflows

### Viewing All Tasks

```python
from hud_controller.spec import PROBLEM_REGISTRY

for problem in PROBLEM_REGISTRY:
    print(f"{problem.id} ({problem.difficulty}): {problem.description[:50]}...")
```

### Testing a Specific Task

```bash
# Method 1: Command line
grade_problem <task_id>

# Method 2: Python
python -c "
from hud_controller.app import grade_problem_script
import sys
sys.argv = ['', 'task_id']
grade_problem_script()
"
```

### Debugging Failed Grading

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run grading with verbose output
grade_problem my_task 2>&1 | tee grading.log

# Check the log for:
# - Build errors
# - Test failures
# - Patch application issues
```

## Project Structure

```
.
├── src/hud_controller/
│   ├── app.py                  # Main entry point
│   ├── grading_runner.py       # Test execution logic
│   ├── spec.py                 # Core definitions
│   ├── graders.py              # Grading implementations
│   └── extractors/             # Task definitions
│       ├── basic_tasks.py      # Easy tasks
│       ├── medium_tasks.py     # Medium tasks
│       └── hard_tasks.py       # Hard tasks
├── README.md                   # Architecture overview
├── SETUP_GUIDE.md             # Detailed setup instructions
├── CUSTOMIZATION_GUIDE.md     # How to customize
└── QUICKSTART.md              # This file
```

## Task Creation Template

Copy this template for new tasks:

```python
@problem(
    id="<unique_id>",
    description="""
    [Clear description of what needs to be fixed/implemented]
    
    Current behavior: [what happens now]
    Expected behavior: [what should happen]
    Location: [file path]
    """,
    hints=[],
    difficulty="easy",  # or "medium", "hard"
    task_type="coding",
    review_level="no-review",
    base="<task>_baseline",
    test="<task>_test",
    golden="<task>_golden",
)
def <unique_id>(state: EnvironmentState) -> Grade:
    """Task: [One-line description]"""
    return Grade.from_subscores([
        AgentPatchGrader.grade(
            state=state,
            weight=1.0,
            base="<task>_baseline",
            test="<task>_test",
            golden="<task>_golden",
            jest_test_files=["path/to/test.ts"],
        )
    ])
```

## Troubleshooting

### Build Fails

```bash
# Check baseline builds
cd /path/to/repo
git checkout my_task_baseline
npm run build  # or your build command

# Check test branch builds
git checkout my_task_test
npm run build
```

### Tests Don't Run

```bash
# Verify test file exists
git checkout my_task_test
ls -l path/to/test.ts

# Run tests manually
npm test -- path/to/test.ts
```

### Grading Times Out

```python
# In grading_runner.py, increase timeout
def _wait_for_server(self, timeout: int = 1200):  # 20 minutes
    ...
```

### Database Issues

```bash
# Check PostgreSQL is running
pg_isready

# Check database exists
psql -l | grep your_test_db

# Reset database manually
dropdb your_test_db && createdb your_test_db
```

## Next Steps

1. **Read SETUP_GUIDE.md** for detailed configuration options
2. **Review example tasks** in `src/hud_controller/extractors/`
3. **Customize for your project** using CUSTOMIZATION_GUIDE.md
4. **Create more tasks** to build your evaluation suite

## Quick Reference

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `REPO_PATH` | Path to target repository | `/home/user/myproject` |
| `TEST_DB_NAME` | Test database name | `myproject_test` |
| `MCP_TESTING_MODE` | Enable testing tools | `1` |
| `LOG_LEVEL` | Logging verbosity | `DEBUG` |

### Common Commands

```bash
# Install
pip install -e .

# List tasks
python -c "from hud_controller.spec import PROBLEM_REGISTRY; [print(p.id) for p in PROBLEM_REGISTRY]"

# Grade a task
grade_problem <task_id>

# Run all tasks
python -m hud_controller.app
```

### Task Difficulty Guidelines

- **Easy**: Single file, <30 min, clear fix
- **Medium**: 2-4 files, ~1 hour, moderate complexity
- **Hard**: Multiple files, 2+ hours, architectural changes

## Getting Help

1. Check logs: `grade_problem task_id 2>&1 | tee debug.log`
2. Review example tasks in `extractors/`
3. Read detailed guides:
   - SETUP_GUIDE.md - Configuration
   - CUSTOMIZATION_GUIDE.md - Adaptation
   - README.md - Architecture

## Example Session

Here's what a typical session looks like:

```bash
$ export REPO_PATH=/home/user/myproject
$ export TEST_DB_NAME=myproject_test

$ grade_problem fix_login_bug
[INFO] Starting grading workflow
[INFO] Copying repo to /tmp/grading_workspace_abc123
[INFO] Applying test patch
[INFO] Compiling project
[INFO] Running tests
[INFO] Tests completed with code: 0
[INFO] Grade: 1.0 (Success!)
```

You're now ready to create evaluation tasks! Start with easy tasks to get comfortable, then progress to more complex scenarios.

