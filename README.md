# Agent Evaluation Framework Template

## Overview

This is a template framework for creating and evaluating AI agent tasks. It provides a structured approach to:
- Define coding tasks with clear specifications
- Grade agent solutions automatically using test-based validation
- Manage multiple task difficulties (easy, medium, hard)
- Run tasks in isolated environments with proper grading

## Project Structure

```
.
├── src/hud_controller/          # Main framework code
│   ├── app.py                   # Main MCP server and entry points
│   ├── spec.py                  # Core specifications (Problem, Grade, Grader)
│   ├── graders.py               # Grading implementations
│   ├── grading_runner.py        # Test execution and grading logic
│   ├── utils.py                 # Utility functions
│   ├── setup.py                 # Environment setup
│   ├── extractors/              # Task definitions by difficulty
│   │   ├── basic_tasks.py       # Easy difficulty tasks
│   │   ├── medium_tasks.py      # Medium difficulty tasks
│   │   └── hard_tasks.py        # Hard difficulty tasks
│   └── tools/                   # MCP tools for testing
│       ├── base.py              # Base tool definitions
│       ├── bash.py              # Bash execution
│       ├── computer.py          # Computer interaction
│       ├── edit.py              # File editing
│       └── run.py               # Command running
├── pyproject.toml               # Python package configuration
├── Dockerfile                   # Container setup
└── README.md                    # This file
```

## Core Concepts

### 1. Problem Definition

Problems are defined using the `@problem` decorator with these key fields:

```python
@problem(
    id="unique_task_id",
    description="Detailed task description",
    hints=[],  # Optional hints for agents
    difficulty="easy",  # or "medium", "hard"
    task_type="coding",
    review_level="no-review",  # or other review levels
    base="baseline_branch",
    test="test_branch", 
    golden="golden_solution_branch",
)
def task_name(state: EnvironmentState) -> Grade:
    """Task implementation"""
    # Return grade based on test results
```

### 2. Grading System

The framework uses a sophisticated grading system:

- **Grader**: Base class for all graders
- **SubGrade**: Individual grading component with score and weight
- **Grade**: Final grade computed from multiple SubGrades
- **AgentPatchGrader**: Tests agent solutions by applying patches and running tests

### 3. Test-Based Validation

Tasks are graded by:
1. Copying the repository to a clean workspace
2. Applying a test patch (adds failing tests)
3. Applying the agent's solution patch
4. Running specified test files
5. Parsing JUnit XML results to determine pass/fail

## Creating New Tasks

### Step 1: Choose Difficulty Level

Place your task in the appropriate file:
- `extractors/basic_tasks.py` - Easy tasks
- `extractors/medium_tasks.py` - Medium tasks  
- `extractors/hard_tasks.py` - Hard tasks

### Step 2: Define the Task

```python
@problem(
    id="my_task",
    description="Clear description of what needs to be implemented",
    hints=[
        HintSpec(
            hint_type="legit",  # or "leaky"
            text="Helpful hint text",
            why_legitmate="Explanation of why this hint is fair"
        )
    ],
    difficulty="easy",
    task_type="coding",
    review_level="no-review",
    base="my_task_baseline",
    test="my_task_test",
    golden="my_task_golden",
)
def my_task(state: EnvironmentState) -> Grade:
    """
    Task: Description
    
    :param state: The current state of the environment after the agent has worked
    
    Returns:
        Grade: Score (0.0 to 1.0) based on test results
    
    Grading:
        - Full score (1.0): All tests pass
        - Zero score (0.0): Tests fail
    """
    return Grade.from_subscores([
        AgentPatchGrader.grade(
            state=state,
            weight=1.0,
            base="my_task_baseline",
            test="my_task_test",
            golden="my_task_golden",
            jest_test_files=[
                "path/to/test/file.test.ts",
            ],
        )
    ])
```

### Step 3: Prepare Git Branches

You need three branches in your target repository:

1. **baseline** - Starting state with the bug/missing feature
2. **test** - Adds failing tests that verify the fix
3. **golden** - Contains the correct solution (for reference)

### Step 4: Configure Test Files

Specify which test files should run:
- `jest_test_files` - For Jest/TypeScript tests
- `playwright_test_files` - For Playwright e2e tests (if supported)
- `mocha_test_files` - For Mocha tests (if supported)

## Running Tasks

### Setup Environment

```bash
# Install dependencies
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Run Grading

```bash
# Run a specific problem
setup_problem <problem_id>
grade_problem <problem_id>

# Or use the main entry point
hud_eval
```

## Grading Runner Details

The `GradingRunner` class handles the entire grading workflow:

1. **Workspace Preparation**: Copies repository to isolated workspace
2. **Patch Application**: Applies test patch, then agent solution
3. **Build Process**: Compiles the project (with cleanup of generated files)
4. **Database Setup**: Resets test database and runs migrations (if applicable)
5. **Server Management**: Optionally starts server (version-dependent)
6. **Test Execution**: Runs specified test files
7. **Result Collection**: Parses JUnit XML results
8. **Cleanup**: Stops servers and cleans up resources

## Configuration

### Environment Variables

Key environment variables used by the grading system:

- `MCP_TESTING_MODE` - Enable testing tools (default: "1")
- `NODE_ENV` - Node environment (set to "test" for testing)
- `WEBHOOK_FAILURE_TIME_WINDOW` - Example task-specific config
- `WEBHOOK_FAILURE_RATE_THRESHOLD` - Example task-specific config

### Docker Configuration

The included `Dockerfile` sets up the complete environment:
- Base system with required tools
- Database (PostgreSQL)
- Redis
- Node.js/Yarn
- VNC for GUI testing (if needed)

## Testing Framework Integration

The framework currently supports Jest tests with JUnit XML output:

```javascript
// jest.config.js should include:
reporters: [
  'default',
  ['jest-junit', {
    outputDirectory: '.',
    outputName: 'jest_results.xml',
  }]
]
```

## Best Practices

### Task Design

1. **Clear Descriptions**: Provide detailed, unambiguous task descriptions
2. **Focused Scope**: Each task should test one concept or skill
3. **Realistic Scenarios**: Base tasks on real-world debugging/development scenarios
4. **Fair Hints**: If providing hints, ensure they guide without giving away the solution

### Test Design

1. **Comprehensive Coverage**: Tests should fully validate the requirement
2. **Clear Failures**: Test failures should clearly indicate what's wrong
3. **Minimal Changes**: Test patches should only add tests, not modify existing code
4. **Isolation**: Tests should not depend on external state

### Branch Management

1. **Clean Baseline**: Baseline should be stable and buildable
2. **Minimal Test Patch**: Only add tests that verify the specific requirement
3. **Correct Golden**: Golden solution should be minimal and idiomatic

## Extending the Framework

### Adding New Graders

Create a new grader by extending the `Grader` base class:

```python
class CustomGrader(Grader):
    name = "CustomGrader"
    
    @classmethod
    def compute_score(cls, state: EnvironmentState, **kwargs) -> float:
        # Your grading logic here
        return score  # 0.0 to 1.0
```

### Adding New Test Frameworks

Modify `GradingRunner` to support additional test frameworks:

1. Add test file parameter to `__init__`
2. Create test execution method (similar to `run_jest_tests`)
3. Ensure JUnit XML output
4. Update `run_grading` to call new test method

## Troubleshooting

### Build Failures

- Check that baseline branch compiles successfully
- Verify no generated files interfere (runner cleans up `.js` files from `.ts` sources)
- Review build logs in stderr output

### Test Failures

- Verify test patch applies cleanly to baseline
- Check that tests fail on baseline + test patch
- Confirm tests pass on baseline + test + golden patches
- Review JUnit XML output for specific failures

### Server Issues

- Check version detection logic if server won't start
- Verify database migrations run successfully
- Ensure server port (3000) is available

## License

This framework template is provided for guidance purposes. Customize as needed for your specific evaluation requirements.

## Support

For questions or issues:
1. Review the example tasks in `extractors/` directories
2. Check the grading logic in `grading_runner.py`
3. Examine the problem decorator in `spec.py`

