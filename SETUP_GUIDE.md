# Setup Guide: Adapting This Template for Your Project

This guide walks you through the process of adapting this evaluation framework template for your own codebase and task creation.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Configuration](#initial-configuration)
3. [Repository Setup](#repository-setup)
4. [Creating Your First Task](#creating-your-first-task)
5. [Testing Your Task](#testing-your-task)
6. [Advanced Configuration](#advanced-configuration)
7. [Common Issues](#common-issues)

## Prerequisites

### Required Software

- Python 3.11 or higher
- Git
- Docker (for containerized deployment)
- Node.js and Yarn (if evaluating JavaScript/TypeScript projects)
- PostgreSQL (if your project uses databases)

### Required Knowledge

- Git branching and patches
- Basic understanding of your project's build system
- Test framework used by your project (Jest, pytest, etc.)
- Basic Python programming

## Initial Configuration

### 1. Clone the Template

```bash
git clone <this-template-repo>
cd <template-directory>
```

### 2. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e ".[dev]"
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Path to your target repository
export REPO_PATH="/path/to/your/repo"

# Database configuration (if needed)
export TEST_DB_NAME="your_test_db"
export PGUSER="your_db_user"
export PGPASSWORD="your_db_password"

# Testing mode
export MCP_TESTING_MODE="1"
```

### 4. Update Package Metadata

Edit `pyproject.toml`:

```toml
[project]
name = "your-project-evaluation"
version = "0.1.0"
description = "Evaluation framework for [Your Project]"
```

## Repository Setup

### Understanding the Branch Structure

For each task, you need three branches:

```
baseline → test → golden
```

1. **baseline**: The starting state (with bug or missing feature)
2. **test**: Adds failing tests that validate the fix
3. **golden**: Contains the correct solution

### Creating Task Branches

Let's walk through creating branches for a sample task.

#### Step 1: Create Baseline Branch

```bash
cd /path/to/your/repo

# Create baseline from main/master or specific commit
git checkout -b my_task_baseline main

# Optionally introduce a bug or remove a feature if needed
# ... make changes ...

git commit -m "Add baseline for my_task"
git push origin my_task_baseline
```

#### Step 2: Create Test Branch

```bash
# Branch from baseline
git checkout -b my_task_test my_task_baseline

# Create/modify test files that will fail without the fix
# Example: create tests/test_my_feature.test.ts
```

Example test file:
```typescript
describe('MyFeature', () => {
  it('should handle special case correctly', () => {
    // This test will fail on baseline
    const result = myFeature.handleSpecialCase();
    expect(result).toBe('correct');
  });
});
```

```bash
# Commit the test
git add tests/
git commit -m "Add failing tests for my_task"
git push origin my_task_test
```

#### Step 3: Create Golden Branch

```bash
# Branch from test
git checkout -b my_task_golden my_task_test

# Implement the correct solution
# ... make changes to fix the issue ...

git add .
git commit -m "Implement solution for my_task"
git push origin my_task_golden
```

#### Step 4: Verify Branch Structure

```bash
# Test that baseline builds but tests fail
git checkout my_task_test
npm test  # or your test command - should fail

# Test that golden builds and tests pass
git checkout my_task_golden
npm test  # or your test command - should pass
```

## Creating Your First Task

### 1. Choose Task Difficulty

Decide if your task is easy, medium, or hard:

- **Easy**: Single file, straightforward fix, <30 minutes
- **Medium**: Multiple files, requires understanding system, ~1 hour
- **Hard**: Complex feature, architectural changes, 2+ hours

### 2. Define the Task

Open the appropriate file:
- `src/hud_controller/extractors/basic_tasks.py` (easy)
- `src/hud_controller/extractors/medium_tasks.py` (medium)
- `src/hud_controller/extractors/hard_tasks.py` (hard)

Add your task using the template:

```python
@problem(
    id="fix_login_validation",
    description="""
    Fix login validation to properly handle email addresses with plus signs.
    
    Current behavior: Emails like "user+tag@example.com" are rejected as invalid.
    Expected behavior: All valid RFC-compliant emails should be accepted.
    
    Location: src/auth/validators.ts
    
    The email validation regex needs to be updated to allow plus signs in the
    local part of the email address.
    """,
    hints=[],
    difficulty="easy",
    task_type="coding",
    review_level="no-review",
    base="fix_login_validation_baseline",
    test="fix_login_validation_test",
    golden="fix_login_validation_golden",
)
def fix_login_validation(state: EnvironmentState) -> Grade:
    """
    Task: Fix email validation to allow plus signs
    
    Returns:
        Grade: Score (0.0 to 1.0) based on whether validation is fixed
    
    Grading:
        - 1.0: Validation updated correctly, all tests pass
        - 0.0: Validation incorrect or tests fail
    """
    return Grade.from_subscores([
        AgentPatchGrader.grade(
            state=state,
            weight=1.0,
            base="fix_login_validation_baseline",
            test="fix_login_validation_test",
            golden="fix_login_validation_golden",
            jest_test_files=[
                "src/auth/__tests__/validators.test.ts",
            ],
        )
    ])
```

### 3. Configure Test Framework

#### For Jest (JavaScript/TypeScript)

Ensure your `jest.config.js` includes JUnit reporter:

```javascript
module.exports = {
  // ... other config ...
  reporters: [
    'default',
    ['jest-junit', {
      outputDirectory: '.',
      outputName: 'jest_results.xml',
      classNameTemplate: '{classname}',
      titleTemplate: '{title}',
      ancestorSeparator: ' › ',
      usePathForSuiteName: true,
    }]
  ],
};
```

Install the reporter:
```bash
npm install --save-dev jest-junit
```

#### For pytest (Python)

Ensure pytest is configured for JUnit output:

```python
# In GradingRunner, update the test command:
result = subprocess.run(
    ["pytest", "--junit-xml=pytest_results.xml"] + self.pytest_test_files,
    cwd=self.grade_working_dir,
    capture_output=True,
    text=True,
)
```

### 4. Update GradingRunner (if needed)

If your project uses a different test framework, update `grading_runner.py`:

```python
def run_your_tests(self) -> str:
    """Run your test framework and return JUnit XML"""
    logger.info(f"Running tests in {self.grade_working_dir}")
    
    # Customize this command for your test framework
    test_command = f"your-test-command --xml-output {' '.join(self.test_files)}"
    
    result = subprocess.run(
        ["sudo", "-u", "ubuntu", "bash", "-lc", test_command],
        cwd=Path(self.grade_working_dir),
        capture_output=True,
        text=True,
    )
    
    logger.info(f"Tests completed with code: {result.returncode}")
    
    # Read and return the XML results
    with open(Path(self.grade_working_dir) / "test_results.xml") as f:
        return f.read()
```

Then update `run_grading()` to call your test method:

```python
# In run_grading method, replace:
junit_xmls = [self.run_jest_tests()]

# With:
junit_xmls = [self.run_your_tests()]
```

## Testing Your Task

### 1. Register Your Task

Your task is automatically registered when the module is imported. Verify registration:

```python
from hud_controller.spec import PROBLEM_REGISTRY

# List all registered problems
for problem in PROBLEM_REGISTRY:
    print(f"{problem.id}: {problem.difficulty}")
```

### 2. Test Manually

```bash
# Setup the problem (if needed)
setup_problem fix_login_validation

# Grade the problem
grade_problem fix_login_validation
```

### 3. Verify Grading Logic

Test the grading workflow step by step:

```bash
# In Python:
from hud_controller.grading_runner import GradingRunner

runner = GradingRunner(
    base="fix_login_validation_baseline",
    test="fix_login_validation_test",
    golden="fix_login_validation_golden",
    jest_test_files=["src/auth/__tests__/validators.test.ts"],
)

success, metadata = runner.run_grading()
print(f"Success: {success}")
print(f"Metadata: {metadata}")
```

### 4. Test End-to-End with an Agent

If you have an AI agent that can work on the task:

1. Present the task description to the agent
2. Let the agent modify the code
3. Create a patch from the agent's changes
4. Run the grading workflow with the agent's patch

## Advanced Configuration

### Custom Graders

Create custom graders for specific validation needs:

```python
from hud_controller.spec import Grader, EnvironmentState

class CustomGrader(Grader):
    name = "CustomGrader"
    
    @classmethod
    def compute_score(cls, state: EnvironmentState, **kwargs) -> float:
        """
        Custom grading logic.
        
        Example: Check if a specific file contains certain code
        """
        import os
        
        file_path = kwargs.get('file_path')
        required_content = kwargs.get('required_content')
        
        if not os.path.exists(file_path):
            return 0.0
        
        with open(file_path) as f:
            content = f.read()
            if required_content in content:
                return 1.0
        
        return 0.0

# Use in task definition:
return Grade.from_subscores([
    CustomGrader.grade(
        state=state,
        weight=0.3,
        file_path="src/config.ts",
        required_content="export const API_VERSION",
    ),
    AgentPatchGrader.grade(
        state=state,
        weight=0.7,
        # ... test config
    ),
])
```

### Multi-Component Grading

For tasks with multiple independent components:

```python
return Grade.from_subscores([
    AgentPatchGrader.grade(
        state=state,
        weight=0.4,
        base="task_baseline",
        test="task_test",
        golden="task_golden",
        jest_test_files=["tests/component1.test.ts"],
    ),
    AgentPatchGrader.grade(
        state=state,
        weight=0.3,
        base="task_baseline",
        test="task_test",
        golden="task_golden",
        jest_test_files=["tests/component2.test.ts"],
    ),
    AgentPatchGrader.grade(
        state=state,
        weight=0.3,
        base="task_baseline",
        test="task_test",
        golden="task_golden",
        jest_test_files=["tests/integration.test.ts"],
    ),
])
```

### Conditional Server Starting

Some projects need a server running during tests, others don't. Configure this:

```python
# In grading_runner.py, update _needs_server_start():

def _needs_server_start(self) -> bool:
    """Determine if server should start based on your criteria"""
    
    # Option 1: Always need server
    return True
    
    # Option 2: Never need server
    return False
    
    # Option 3: Version-based (as in template)
    package_json_path = Path(self.grade_working_dir) / "package.json"
    with open(package_json_path) as f:
        package_data = json.load(f)
    current_version = package_data.get("version", "0.0.0")
    return version.parse(current_version) <= version.parse("1.0.0")
    
    # Option 4: Environment variable
    return os.environ.get("NEEDS_SERVER", "false") == "true"
```

### Database Migrations

Customize database setup for your project:

```python
# In run_grading method, update migration commands:

# For Prisma:
migrate_cmd = "npx prisma migrate deploy"

# For Django:
migrate_cmd = "python manage.py migrate --noinput"

# For Rails:
migrate_cmd = "bundle exec rake db:migrate"

# For custom SQL:
migrate_cmd = "psql -h localhost -U user -d testdb -f migrations/all.sql"
```

## Common Issues

### Issue: Tests Pass on Baseline

**Problem**: Tests aren't actually validating the requirement.

**Solution**: 
1. Check that test branch is correctly based on baseline
2. Verify test actually fails without the fix
3. Ensure test is checking the right behavior

### Issue: Build Fails

**Problem**: Compilation errors prevent tests from running.

**Solution**:
1. Verify baseline builds successfully alone
2. Check for conflicts between test and baseline branches
3. Review build logs in grading output

### Issue: Tests Timeout

**Problem**: Tests hang or run indefinitely.

**Solution**:
1. Add timeout to test runner configuration
2. Check for infinite loops in test setup
3. Ensure database/server cleanup happens properly

### Issue: Database Errors

**Problem**: Database connection or migration failures.

**Solution**:
1. Verify PostgreSQL is running: `pg_isready`
2. Check database credentials in environment
3. Ensure database user has necessary permissions
4. Review migration scripts for errors

### Issue: Incorrect Grading

**Problem**: Task is graded incorrectly (false positive/negative).

**Solution**:
1. Test golden branch manually - should pass all tests
2. Test baseline + test branch manually - should fail tests
3. Review JUnit XML output for details
4. Add logging to grading logic

## Next Steps

1. **Create More Tasks**: Start with easy tasks to get comfortable
2. **Validate Task Quality**: Have others attempt your tasks
3. **Document Patterns**: Note common issues and solutions
4. **Automate Testing**: Set up CI/CD for task validation
5. **Scale Up**: Create harder, more realistic tasks

## Support Resources

- Review example tasks in `extractors/` for patterns
- Check `grading_runner.py` for grading workflow
- Examine `spec.py` for decorator and grading structure
- Read `README.md` for architecture overview

## Contributing Tasks

When creating tasks for evaluation:

1. **Clear Requirements**: Describe exactly what needs to be done
2. **Focused Scope**: One clear objective per task
3. **Realistic Scenarios**: Based on actual development work
4. **Comprehensive Tests**: Cover main case and edge cases
5. **Fair Difficulty**: Difficulty should match time estimate

Happy task creation!

