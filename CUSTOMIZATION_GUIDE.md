# Customization Guide: Removing Copyrighted Content

This guide explains how to customize this template for your specific project and remove any references to copyrighted materials.

## Overview

This template was created from an evaluation framework originally designed for a specific open-source project. This guide helps you:

1. Remove all project-specific references
2. Adapt the structure for your codebase
3. Maintain clean, reusable evaluation infrastructure
4. Avoid copyright issues when sharing with clients

## Step-by-Step Customization

### 1. Project Naming and Branding

#### Update Package Name

Edit `pyproject.toml`:

```toml
[project]
name = "your-company-evaluation-framework"  # Change from generic name
version = "0.1.0"
description = "AI Agent Evaluation Framework for [Your Project]"
```

#### Update Repository References

Search and replace project-specific paths throughout the codebase:

```bash
# Find all hardcoded references
grep -r "outline" src/
grep -r "ubuntu" src/

# Replace with your project specifics
# Example: replace "outline" with your project name
find src/ -type f -exec sed -i 's/outline/yourproject/g' {} +
```

### 2. Environment Configuration

#### Update Default Paths

In `src/hud_controller/grading_runner.py`:

```python
# OLD (template):
self.original_repo_path = os.environ.get("REPO_PATH", "/home/ubuntu/repo")

# NEW (your project):
self.original_repo_path = os.environ.get("REPO_PATH", "/path/to/your/project")
```

#### Update Database Names

```python
# OLD:
db_name = os.environ.get("TEST_DB_NAME", "test_db")

# NEW:
db_name = os.environ.get("TEST_DB_NAME", "your_project_test")
```

#### Update User Context

If your project doesn't run as a specific user:

```python
# OLD:
subprocess.run(["sudo", "-u", "ubuntu", "bash", "-lc", command], ...)

# NEW (no sudo):
subprocess.run(["bash", "-lc", command], ...)

# OR (different user):
subprocess.run(["sudo", "-u", "youruser", "bash", "-lc", command], ...)
```

### 3. Remove Example Tasks

The template includes example tasks in `src/hud_controller/extractors/`. You have two options:

#### Option A: Keep as Templates (Recommended)

Leave the example tasks as reference templates. They show the structure clearly and don't execute unless explicitly called.

#### Option B: Remove Completely

If you want a completely clean slate:

```python
# In basic_tasks.py, medium_tasks.py, hard_tasks.py
# Delete all @problem definitions except the template comments

# Keep only:
import logging

from hud_controller.graders import AgentPatchGrader
from hud_controller.spec import EnvironmentState, Grade, problem

logger = logging.getLogger(__name__)

# Add your tasks here following the template structure in comments
```

### 4. Customize Build Process

#### Update Build Commands

In `grading_runner.py`, update the build command for your project:

```python
# OLD (Node.js/Yarn):
build_process = subprocess.Popen(
    ["sudo", "-u", "ubuntu", "bash", "-lc", 
     "NODE_OPTIONS=\"--max-old-space-size=4096\" yarn build"],
    ...
)

# NEW (Python/pip):
build_process = subprocess.Popen(
    ["python", "-m", "pip", "install", "-e", "."],
    ...
)

# NEW (Maven):
build_process = subprocess.Popen(
    ["mvn", "clean", "package", "-DskipTests"],
    ...
)

# NEW (Go):
build_process = subprocess.Popen(
    ["go", "build", "./..."],
    ...
)
```

#### Remove Cleanup Steps

If you don't need JavaScript cleanup:

```python
# In run_grading method, remove or comment out:
# self._cleanup_generated_js_files()

# Or adapt for your needs:
def _cleanup_generated_files(self):
    """Remove generated files that interfere with build"""
    # Your custom cleanup logic
    pass
```

### 5. Adapt Test Framework

#### Configure for Your Test Framework

Update `run_grading()` to use your test runner:

```python
# For Jest (already configured):
junit_xmls = [self.run_jest_tests()]

# For pytest:
def run_pytest_tests(self) -> str:
    logger.info(f"Running pytest in {self.grade_working_dir}")
    result = subprocess.run(
        ["pytest", "--junit-xml=pytest_results.xml"] + self.test_files,
        cwd=self.grade_working_dir,
        capture_output=True,
        text=True,
    )
    with open(Path(self.grade_working_dir) / "pytest_results.xml") as f:
        return f.read()

# For JUnit/TestNG:
def run_junit_tests(self) -> str:
    logger.info(f"Running JUnit tests in {self.grade_working_dir}")
    result = subprocess.run(
        ["mvn", "test", "-Dtest=" + ",".join(self.test_files)],
        cwd=self.grade_working_dir,
        capture_output=True,
        text=True,
    )
    with open(Path(self.grade_working_dir) / "target/surefire-reports/TEST-*.xml") as f:
        return f.read()

# For Go:
def run_go_tests(self) -> str:
    logger.info(f"Running Go tests in {self.grade_working_dir}")
    result = subprocess.run(
        ["go", "test", "-v", "./...", "-json"],
        cwd=self.grade_working_dir,
        capture_output=True,
        text=True,
    )
    # Convert JSON to JUnit XML
    return self._convert_go_json_to_junit(result.stdout)
```

### 6. Database Configuration

#### Adapt or Remove Database Setup

If your project doesn't use a database:

```python
# In run_grading method, comment out or remove:
# Step 5: Reset test database and run migrations
# logger.info(...)
# drop_cmd = ...
# create_cmd = ...
# migrate_cmd = ...
```

If you use a different database:

```python
# For MongoDB:
drop_cmd = f"mongo {db_name} --eval 'db.dropDatabase()'"
create_cmd = f"mongo {db_name} --eval 'db.createCollection(\"init\")'"

# For MySQL:
drop_cmd = f"mysql -u root -p{password} -e 'DROP DATABASE IF EXISTS {db_name}'"
create_cmd = f"mysql -u root -p{password} -e 'CREATE DATABASE {db_name}'"

# For SQLite:
import os
db_path = f"/tmp/{db_name}.db"
if os.path.exists(db_path):
    os.remove(db_path)
```

### 7. Server Management

#### Configure Server Starting

Adapt `_needs_server_start()` for your project:

```python
def _needs_server_start(self) -> bool:
    """Determine if server should start for tests"""
    
    # Option 1: Always start server
    return True
    
    # Option 2: Never start server (tests don't need it)
    return False
    
    # Option 3: Based on environment variable
    return os.environ.get("START_SERVER_FOR_TESTS", "false").lower() == "true"
    
    # Option 4: Based on test types
    # Start server only for integration tests
    return any("integration" in test for test in self.test_files)
```

#### Update Server Start Command

```python
# OLD (Node.js):
self.server_process = subprocess.Popen(
    ["sudo", "-u", "ubuntu", "bash", "-lc", "yarn start"],
    ...
)

# NEW (Django):
self.server_process = subprocess.Popen(
    ["python", "manage.py", "runserver", "3000"],
    ...
)

# NEW (Flask):
self.server_process = subprocess.Popen(
    ["flask", "run", "--port=3000"],
    env={**os.environ, "FLASK_APP": "app.py"},
    ...
)

# NEW (Spring Boot):
self.server_process = subprocess.Popen(
    ["java", "-jar", "target/app.jar", "--server.port=3000"],
    ...
)
```

### 8. Docker Configuration

#### Update Dockerfile

Replace project-specific setup with your requirements:

```dockerfile
# Remove:
# - Outline-specific packages
# - Project-specific configurations
# - Hardcoded paths

# Add:
# - Your project dependencies
# - Your build tools
# - Your database (if needed)

# Example minimal Dockerfile:
FROM ubuntu:22.04

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy evaluation framework
COPY . /evaluation
WORKDIR /evaluation

# Install framework
RUN pip install -e .

# Set environment variables
ENV REPO_PATH=/workspace/repo
ENV MCP_TESTING_MODE=1

CMD ["hud_eval"]
```

### 9. Clean Up Unused Files

#### Identify Project-Specific Files

```bash
# List files that might be project-specific
find . -name "*outline*"
find dinit.d/ -type f  # If you don't need dinit
find docker-entrypoint-initdb.d/  # If you don't need this setup
```

#### Remove or Adapt

- `dinit.d/` - Service initialization (remove if not needed)
- `docker-entrypoint-initdb.d/` - Database init scripts (adapt or remove)
- `build_scripts/` - Build customization (adapt for your project)
- `.dockerignore` - Update for your project structure

### 10. Documentation

#### Update All Documentation

1. **README.md** - Already updated with generic examples
2. **SETUP_GUIDE.md** - Already generic
3. **This file** - Keep as reference for clients
4. **Add PROJECT_SPECIFIC.md** - Document your customizations

Example PROJECT_SPECIFIC.md:

```markdown
# Project-Specific Configuration

## Our Setup

- **Language**: Python 3.11
- **Test Framework**: pytest
- **Database**: PostgreSQL 14
- **Build Tool**: pip

## Environment Variables

- `REPO_PATH`: Path to our project repository
- `TEST_DB_NAME`: Name of test database (default: our_project_test)

## Task Creation

Tasks are in `src/hud_controller/extractors/`:
- `basic_tasks.py`: Simple bug fixes
- `medium_tasks.py`: Feature additions
- `hard_tasks.py`: Complex refactoring

## Running Evaluations

```bash
# Setup
source venv/bin/activate
export REPO_PATH=/path/to/project

# Run single task
grade_problem task_id

# Run all tasks
python -m hud_controller.app
```
```

### 11. Copyright and Licensing

#### Add Your License

Replace or add a LICENSE file:

```
MIT License

Copyright (c) 2025 Your Company

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software...
```

#### Add Copyright Headers

Add headers to your new files:

```python
# Copyright (c) 2025 Your Company
# Licensed under the MIT License

"""
Your module description
"""
```

## Verification Checklist

After customization, verify:

- [ ] No references to original project name
- [ ] All paths updated for your environment
- [ ] Build process works for your project
- [ ] Test framework integration works
- [ ] Database setup (if needed) works
- [ ] Example tasks removed or clearly marked as templates
- [ ] Documentation updated
- [ ] Environment variables documented
- [ ] Docker configuration works (if using Docker)
- [ ] All hardcoded values replaced with configs
- [ ] LICENSE file added/updated
- [ ] README reflects your project

## Search and Replace Checklist

Use these commands to find remaining references:

```bash
# Search for common project-specific terms
grep -ri "outline" . --exclude-dir=venv --exclude-dir=.git
grep -ri "ubuntu" . --exclude-dir=venv --exclude-dir=.git
grep -ri "rocket.chat" . --exclude-dir=venv --exclude-dir=.git

# Search for hardcoded paths
grep -r "/home/ubuntu" . --exclude-dir=venv --exclude-dir=.git
grep -r "/tmp" . --exclude-dir=venv --exclude-dir=.git

# Search for specific port numbers (if you need different ones)
grep -r "3000" . --exclude-dir=venv --exclude-dir=.git
grep -r "8039" . --exclude-dir=venv --exclude-dir=.git
```

## Best Practices for Clients

When delivering to clients:

1. **Provide Both Versions**:
   - Template version (this) - shows structure
   - Configured version - ready to use

2. **Clear Documentation**:
   - Document all customizations made
   - Explain why each change was necessary
   - Provide examples of adding new tasks

3. **Training/Handoff**:
   - Walk through creating a task
   - Demonstrate running evaluations
   - Show how to debug issues

4. **Ongoing Support**:
   - Document common issues
   - Provide troubleshooting guide
   - Include contact for questions

## Conclusion

This template is designed to be easily customizable while maintaining a clear structure. The key is to:

1. Replace all project-specific references
2. Adapt the workflow to your build/test process
3. Keep the core evaluation logic intact
4. Document your customizations

The framework provides flexibility while maintaining a proven structure for agent evaluation.

