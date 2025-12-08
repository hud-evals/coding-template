# Coding Environment Template

## Overview

This is a template framework for creating and evaluating AI agent tasks. It provides a structured approach to:
- Define coding tasks with clear specifications
- Grade agent solutions automatically using test-based validation
- Manage multiple task difficulties (easy, medium, hard)
- Run tasks in isolated environments with proper grading

## Quick Start

```bash
# Build the Docker image
hud build

# Start hot-reload development server
hud dev

# Create your tasks file
uv run utils/imagectl.py -j <image name>

# Run the tasks
hud eval local-hud.json
```

## Deploy

When you're ready to use this environment in production:

1. Push your code to GitHub
2. Connect your repo at [hud.ai](https://hud.ai/environments/new)
3. Builds will trigger automatically on each push

## Tools

- **bash** - Execute shell commands: `bash(command="ls -la")`
- **str_replace_editor** - Edit files: `str_replace_editor(command="view", path="/path/to/file")`
- **computer** - GUI automation: `computer(action="screenshot")`
- **setup_problem** - Initialize task: `setup_problem(problem_id="example_easy_task")`
- **grade_problem** - Evaluate solution: `grade_problem(problem_id="example_easy_task", transcript="...")`

## Cursor Integration

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "coding-template": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "coding-template"]
    }
  }
}
```

## Creating New Tasks

1. Add task definition in `server/problems/` using the `@problem` decorator
2. Create three git branches in your target repo: `baseline`, `test`, `golden`
3. Configure the grading logic to run appropriate tests

```python
@problem(
    id="my_task",
    description="Task description...",
    difficulty="easy",
    base="my_task_baseline",
    test="my_task_test",
    golden="my_task_golden",
)
def my_task(state: EnvironmentState) -> Grade:
    return Grade.from_subscores([
        AgentPatchGrader.grade(state=state, weight=1.0, ...)
    ])
```

## Learn More

Start with [CUSTOMIZATION_GUIDE.md](CUSTOMIZATION_GUIDE.md) for a guide on how to customize this template for your project.

For complete documentation on building environments and running evaluations, visit [docs.hud.ai](https://docs.hud.ai).
