# Customization Guide

This guide explains how to customize this template for your specific project.

## Overview

This framework template can be adapted for any programming language and tech stack. All customization points are marked with `[PLACEHOLDERS]` and extensive comments explaining how to adapt them.

## Quick Start Customization

Follow these steps to adapt the template for your project:

1. **Set Project Name**: Replace `[PROJECT_NAME]` throughout files
2. **Configure Build**: Set build commands in Dockerfile and `environment/grading.py`
3. **Configure Tests**: Set test framework and test commands
4. **Set Database**: Update database names in SQL and env files (or remove if not needed)
5. **Adjust Paths**: Update `/home/ubuntu/[PROJECT_NAME]` paths

## Files to Customize

### 1. Dockerfile

The Dockerfile contains the main project setup section. You need to uncomment and customize:

**Required:**
- Repository cloning (lines 126-135)
- Branch checkout (lines 139-146)
- Language runtime installation (lines 155-193)
- Dependency installation (lines 195-202)
- Test framework configuration (lines 204-229)
- Project build (lines 231-238)

**Examples by Tech Stack:**

#### Node.js/TypeScript
```dockerfile
ARG REPO_PATH=/home/ubuntu/myproject
ENV REPO_PATH=$REPO_PATH

RUN git clone https://github.com/your-org/your-repo $REPO_PATH
WORKDIR $REPO_PATH

# Install Node.js
RUN NODE_VERSION=20 && \
    bash -c "source ~/.nvm/nvm.sh && nvm install $NODE_VERSION && nvm use $NODE_VERSION"
SHELL ["/bin/bash", "--login", "-c"]

# Install dependencies
RUN yarn install

# Configure Jest for JUnit XML output
RUN yarn add jest-junit

# Build
RUN yarn build
```

#### Python
```dockerfile
ARG REPO_PATH=/home/ubuntu/myproject
ENV REPO_PATH=$REPO_PATH

RUN git clone https://github.com/your-org/your-repo $REPO_PATH
WORKDIR $REPO_PATH

# Python is already installed
RUN python3 -m pip install --upgrade pip

# Install dependencies
RUN pip install -r requirements.txt

# Configure pytest for JUnit XML output
RUN pip install pytest-junit
```

#### Java
```dockerfile
ARG REPO_PATH=/home/ubuntu/myproject
ENV REPO_PATH=$REPO_PATH

RUN git clone https://github.com/your-org/your-repo $REPO_PATH
WORKDIR $REPO_PATH

# Maven is already installed
RUN mvn dependency:resolve

# Build (skip tests during build)
RUN mvn package -DskipTests
```

### 2. environment/grading.py

Multiple customization points for test execution and build process:

**Test Command:**
```python
# For Jest:
test_command = f"yarn test -- --runInBand --verbose {' '.join(self.test_files)}"

# For pytest:
test_command = f"pytest --junit-xml=pytest_results.xml {' '.join(self.test_files)}"

# For JUnit (Maven):
test_command = f"mvn test -Dtest={','.join(self.test_files)}"

# For GTest:
test_command = f"./test_runner --gtest_output=xml:gtest_results.xml"
```

**Test Results XML File:**
```python
# For Jest:
xml_file = "jest_results.xml"

# For pytest:
xml_file = "pytest_results.xml"

# For JUnit:
xml_file = "target/surefire-reports/TEST-*.xml"

# For GTest:
xml_file = "gtest_results.xml"
```

**Build Command:**
```python
# For Node.js:
build_command = "NODE_OPTIONS=\"--max-old-space-size=4096\" yarn build"

# For Python (often no build):
build_command = "echo 'No build step required'"

# For Java:
build_command = "mvn package -DskipTests"

# For C++:
build_command = "cd build && cmake .. && make"

# For Rust:
build_command = "cargo build --release"
```

**Migration Command:**
```python
# For Node.js/Sequelize:
migrate_cmd = "export NODE_ENV=test && yarn db:migrate"

# For Django:
migrate_cmd = "python manage.py migrate --noinput"

# For Rails:
migrate_cmd = "bundle exec rake db:migrate"

# Set to None if no migrations:
migrate_cmd = None
```

**Server Start Command:**
```python
# For Node.js:
server_start_cmd = "yarn start"

# For Django:
server_start_cmd = "python manage.py runserver 3000"

# For Flask:
server_start_cmd = "flask run --port=3000"

# For Spring Boot:
server_start_cmd = "java -jar target/app.jar --server.port=3000"
```

### 3. server/problems/

Update the task templates in `server/problems/`:

**basic_tasks.py, medium_tasks.py, hard_tasks.py**

Change `test_files` parameter to match your test file paths:

```python
from environment.graders import AgentPatchGrader
from server.spec import EnvironmentState, Grade, problem

@problem(
    id="my_task",
    description="Fix the bug...",
    difficulty="easy",
    base="my_task_baseline",
    test="my_task_test",
    golden="my_task_golden",
)
def my_task(state: EnvironmentState) -> Grade:
    return Grade.from_subscores([
        AgentPatchGrader.grade(
            state=state,
            weight=1.0,
            base="my_task_baseline",
            test="my_task_test",
            golden="my_task_golden",
            test_files=[
                "tests/test_feature.py",  # For Python
                # or
                "src/test/MyTest.java",  # For Java
                # or
                "test/feature.test.ts",  # For TypeScript
            ],
        )
    ])
```

### 4. server/main.py

Customize the MCP server name and task template:

```python
mcp = FastMCP("your_project_evaluation", port=8039, log_level="DEBUG", debug=True)

# Update the task template for your project:
template = """
You will be working on a task for [YOUR_PROJECT_NAME].
The repository has already been cloned in the environment in /home/ubuntu/[PROJECT_NAME].

[Add your project-specific instructions here]

Use the tools provided to complete the following task:

<STATEMENT>
"""
```

### 5. utils/imagectl.py

The `hud_dict` function generates task configs. Customize `allowed_tools` as needed:

```python
"agent_config": {
    "allowed_tools": ["bash", "str_replace_editor", "computer"],
}
```

### 6. build_scripts/alter_env_files.py

Customize environment file setup:

```python
def main():
    project_dir = os.environ.get("PROJECT_DIR", "/home/ubuntu/myproject")

    upsert_env_variables(
        f"{project_dir}/.env.test",
        {
            "DATABASE_URL": "postgresql://ubuntu:ubuntu@localhost:5432/myproject_test",
            "NODE_ENV": "test",
            "SECRET_KEY": "test-secret-key",
        }
    )

    shutil.copy(f"{project_dir}/.env.test", f"{project_dir}/.env")
```

### 7. docker-entrypoint-initdb.d/01-init.sql

Replace placeholders with your database configuration:

```sql
CREATE USER myuser WITH SUPERUSER PASSWORD 'mypassword';
CREATE DATABASE myuser;
GRANT ALL PRIVILEGES ON DATABASE myuser TO myuser;

CREATE DATABASE myproject_development;
GRANT ALL PRIVILEGES ON DATABASE myproject_development TO myuser;

CREATE DATABASE myproject_test;
GRANT ALL PRIVILEGES ON DATABASE myproject_test TO myuser;
```

Or remove this file entirely if your project doesn't use PostgreSQL.

## Environment Variables

Set these environment variables when running the framework:

```bash
# Required
export REPO_PATH="/path/to/your/repository"

# Optional
export TEST_DB_NAME="myproject_test"
export MCP_TESTING_MODE="1"
export LOG_LEVEL="DEBUG"
```

## Technology-Specific Examples

### Complete Node.js/TypeScript Example

1. **Dockerfile**: Uncomment Node.js sections
2. **environment/grading.py**:
   - `test_command`: Use yarn/jest
   - `xml_file = "jest_results.xml"`
   - `build_command = "yarn build"`
   - Configure migration and server start commands

3. **build_scripts/alter_env_files.py**: Configure `.env.test` with DATABASE_URL, NODE_ENV
4. **docker-entrypoint-initdb.d/01-init.sql**: Set up project databases

### Complete Python Example

1. **Dockerfile**: Comment out Node.js, uncomment Python sections
2. **environment/grading.py**:
   - `test_command = f"pytest --junit-xml=pytest_results.xml {' '.join(self.test_files)}"`
   - `xml_file = "pytest_results.xml"`
   - `build_command = "echo 'No build required'"`
   - Configure migration and server start commands

3. **build_scripts/alter_env_files.py**: Configure with DJANGO_SETTINGS_MODULE, DATABASE_URL
4. **docker-entrypoint-initdb.d/01-init.sql**: Same database setup

### Complete Java Example

1. **Dockerfile**: Uncomment Java sections
2. **environment/grading.py**:
   - `test_command = f"mvn test -Dtest={','.join(self.test_files)}"`
   - `xml_file = "target/surefire-reports/TEST-*.xml"`
   - `build_command = "mvn package -DskipTests"`
   - Configure server start command

3. **build_scripts/alter_env_files.py**: May not be needed; use application.properties instead
4. **docker-entrypoint-initdb.d/01-init.sql**: Same database setup

## Verification Checklist

After customizing, verify:

- [ ] All `[PLACEHOLDERS]` replaced with actual values
- [ ] Build command works in your repository
- [ ] Test command produces JUnit XML output
- [ ] Test XML file path is correct
- [ ] Database setup matches your project (or removed if not needed)
- [ ] Environment files configured correctly
- [ ] Server start command works (if needed)
- [ ] Cleanup logic appropriate for your project (or removed)

## Testing Your Configuration

1. Build the Docker image:
```bash
hud build
```

2. Run a test container:
```bash
docker run -it <your-image> bash
```

3. Manually test each step:
```bash
# Check project is cloned
cd $REPO_PATH
ls -la

# Check build works
[YOUR_BUILD_COMMAND]

# Check tests run
[YOUR_TEST_COMMAND]

# Check XML output exists
ls -la [XML_FILE_PATH]
```

## Common Issues

### Build Fails

- **Issue**: Build command not found
- **Solution**: Check language runtime is installed correctly in Dockerfile

### Tests Don't Run

- **Issue**: Test command fails
- **Solution**: Verify test framework is installed and configured

### XML File Not Found

- **Issue**: Can't read test results
- **Solution**: Check xml_file path matches where your test framework outputs results

### Database Errors

- **Issue**: Can't connect to database
- **Solution**: Verify database setup in 01-init.sql and environment files match

## Summary

The key customization points are:

1. **Dockerfile**: Project setup, dependencies, build
2. **environment/grading.py**: Test execution, build, migrations, server
3. **server/problems/**: Task definitions
4. **server/main.py**: MCP server configuration
5. **build_scripts/alter_env_files.py**: Environment configuration
6. **docker-entrypoint-initdb.d/01-init.sql**: Database initialization

Everything else (Python framework code, tools, utilities) should work as-is without modification.
