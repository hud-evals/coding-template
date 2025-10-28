# Templating Guide

## Overview

This framework template can be adapted for any programming language and tech stack. All customization points are marked with `[PLACEHOLDERS]` and extensive comments explaining how to adapt them.

## Quick Start Customization

Follow these steps to adapt the template for your project:

1. **Set Project Name**: Replace `[PROJECT_NAME]` throughout files
2. **Configure Build**: Set `[BUILD_COMMAND]` in Dockerfile and grading_runner.py
3. **Configure Tests**: Set test framework and `[TEST_COMMAND]`
4. **Set Database**: Update database names in SQL and env files (or remove if not needed)
5. **Adjust Paths**: Update `/home/ubuntu/[PROJECT_NAME]` paths

## Files to Customize

### Core Configuration Files

#### 1. Dockerfile (Lines 117-245)

The Dockerfile contains the main project setup section. You need to uncomment and customize:

**Required:**
- Repository cloning (lines 123-132)
- Branch checkout (lines 136-143)
- Language runtime installation (lines 155-174)
- Build tool installation (lines 176-193)
- Dependency installation (lines 195-202)
- Test framework configuration (lines 204-229)
- Project build (lines 231-238)

**Examples by Tech Stack:**

##### Node.js/TypeScript
```dockerfile
# Clone repo
RUN git clone https://github.com/your-org/your-repo /home/ubuntu/myproject

WORKDIR /home/ubuntu/myproject

# Install Node.js
RUN NODE_VERSION=20 && \
    bash -c "source ~/.nvm/nvm.sh && nvm install $NODE_VERSION && nvm use $NODE_VERSION"
SHELL ["/bin/bash", "--login", "-c"]

# Install Yarn
RUN npm install -g yarn@1.22.22

# Install dependencies
RUN yarn install

# Configure Jest
RUN yarn add jest-junit && \
    jq '.reporters = ["default", ["jest-junit", {"outputDirectory": "./", "outputName": "jest_results.xml"}]]' .jestconfig.json > .jestconfig.tmp && \
    mv .jestconfig.tmp .jestconfig.json

# Build
RUN yarn build
```

##### Python
```dockerfile
# Clone repo
RUN git clone https://github.com/your-org/your-repo /home/ubuntu/myproject

WORKDIR /home/ubuntu/myproject

# Python is already installed
RUN python3 -m pip install --upgrade pip

# Install dependencies
RUN pip install -r requirements.txt

# Configure pytest
RUN pip install pytest-junit && \
    echo "[tool.pytest.ini_options]" >> pyproject.toml && \
    echo "junit_family = 'xunit2'" >> pyproject.toml

# No build step needed for most Python projects
```

##### Java
```dockerfile
# Clone repo
RUN git clone https://github.com/your-org/your-repo /home/ubuntu/myproject

WORKDIR /home/ubuntu/myproject

# Maven is already installed
# Install dependencies
RUN mvn dependency:resolve

# Configure JUnit XML output (already configured in most Maven projects)

# Build (skip tests during build)
RUN mvn package -DskipTests
```

##### C++
```dockerfile
# Clone repo
RUN git clone https://github.com/your-org/your-repo /home/ubuntu/myproject

WORKDIR /home/ubuntu/myproject

# gcc/g++/cmake already installed
# Create build directory
RUN mkdir build && cd build && cmake .. && make
```

#### 2. grading_runner.py

Multiple customization points for test execution and build process:

**Line 120: Test Command**
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

**Line 134: Test Results XML File**
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

**Line 237: Build Command**
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

**Line 304: Migration Command**
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

**Line 321: Server Start Command**
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

**Line 185: Cleanup Generated Files (Optional)**
```python
# For TypeScript projects that generate JS files:
def _cleanup_generated_files(self):
    # Find and remove .js files that have corresponding .ts files
    # (your implementation here)

# For Python:
def _cleanup_generated_files(self):
    subprocess.run(["find", ".", "-name", "*.pyc", "-delete"], cwd=self.grade_working_dir)
    subprocess.run(["find", ".", "-name", "__pycache__", "-type", "d", "-delete"], cwd=self.grade_working_dir)

# If no cleanup needed:
def _cleanup_generated_files(self):
    pass
```

#### 3. setup.py

**Line 46: Project Directory**
```python
# Customize the default project directory
project_dir = os.environ.get("PROJECT_DIR", "/home/ubuntu/myproject")
```

**Lines 49-67: Makefile Cleanup (Optional)**
```python
# If your project has a Makefile with problematic lines:
pattern_to_remove = "docker compose"  # Change to match your pattern

# Or skip entirely by commenting out this section
```

**Lines 80-83: Hosts Entry (Optional)**
```python
# If your project needs a custom domain:
with open("/etc/hosts", "a") as hosts_file:
    hosts_file.write("127.0.0.1 myproject.local\n")
```

#### 4. build_scripts/alter_env_files.py

Customize the `main()` function to set up your environment files:

```python
def main():
    project_dir = os.environ.get("PROJECT_DIR", "/home/ubuntu/myproject")
    
    # Example for Node.js:
    upsert_env_variables(
        f"{project_dir}/.env.test",
        {
            "DATABASE_URL": "postgresql://ubuntu:ubuntu@localhost:5432/myproject_test",
            "NODE_ENV": "test",
            "SECRET_KEY": "test-secret-key",
        }
    )
    
    # Copy to .env
    shutil.copy(f"{project_dir}/.env.test", f"{project_dir}/.env")
```

#### 5. docker-entrypoint-initdb.d/01-init.sql

Replace placeholders with your database configuration:

```sql
-- Example:
CREATE USER myuser WITH SUPERUSER PASSWORD 'mypassword';
CREATE DATABASE myuser;
GRANT ALL PRIVILEGES ON DATABASE myuser TO myuser;

CREATE DATABASE myproject_development;
GRANT ALL PRIVILEGES ON DATABASE myproject_development TO myuser;

CREATE DATABASE myproject_test;
GRANT ALL PRIVILEGES ON DATABASE myproject_test TO myuser;
```

Or remove this file entirely if your project doesn't use PostgreSQL.

### Task Template Files

Update the task templates in `src/hud_controller/extractors/`:

**basic_tasks.py, medium_tasks.py, hard_tasks.py**

Change `test_files` parameter to match your test file paths:

```python
test_files=[
    "tests/test_feature.py",  # For Python
    # or
    "src/test/MyTest.java",  # For Java
    # or
    "test/feature.test.ts",  # For TypeScript
]
```

### Additional Configuration Files

**src/hud_controller/app.py**

Line 22: Customize the MCP server name:
```python
mcp = FastMCP("your_project_evaluation", port=8039, log_level="DEBUG", debug=True)
```

Lines 127-141: Update the task template for your project:
```python
template = """
You will be working on a task for [YOUR_PROJECT_NAME].
The repository has already been cloned in the environment in /home/ubuntu/[PROJECT_NAME].

[Add your project-specific instructions here]

Use the tools provided to complete the following task:

<STATEMENT>
"""
```

**utils/imagectl.py**

Line 250-260: Update problem set metadata:
```python
out = {
    "problem_set": {
        "owner": "your-organization",
        "name": "your-problem-set-name",
        "version": "1.0.0",
        "description": "Your problem set description",
        "metadata": {"category": "coding", "language": "python", "difficulty": "medium"},
        "problems": [],
    }
}
```

## Environment Variables

Set these environment variables when running the framework:

```bash
# Required
export REPO_PATH="/path/to/your/repository"
export PROJECT_DIR="/home/ubuntu/myproject"

# Optional
export TEST_DB_NAME="myproject_test"
export MCP_TESTING_MODE="1"
```

## Technology-Specific Examples

### Complete Node.js/TypeScript Example

1. **Dockerfile**: Uncomment Node.js sections (lines 157-162, 178-184)
2. **grading_runner.py**:
   - Line 120: `test_command = f"yarn test -- {' '.join(self.test_files)}"`
   - Line 134: `xml_file = "jest_results.xml"`
   - Line 237: `build_command = "yarn build"`
   - Line 304: `migrate_cmd = "yarn db:migrate"`
   - Line 321: `server_start_cmd = "yarn start"`

3. **setup.py**: Line 46: `project_dir = "/home/ubuntu/myproject"`
4. **alter_env_files.py**: Configure `.env.test` with DATABASE_URL, NODE_ENV
5. **01-init.sql**: Set up myproject_development and myproject_test databases

### Complete Python Example

1. **Dockerfile**: Comment out Node.js, uncomment Python sections
2. **grading_runner.py**:
   - Line 120: `test_command = f"pytest --junit-xml=pytest_results.xml {' '.join(self.test_files)}"`
   - Line 134: `xml_file = "pytest_results.xml"`
   - Line 237: `build_command = "echo 'No build required'"`
   - Line 304: `migrate_cmd = "python manage.py migrate"`
   - Line 321: `server_start_cmd = "python manage.py runserver 3000"`

3. **setup.py**: Same as Node.js
4. **alter_env_files.py**: Configure with DJANGO_SETTINGS_MODULE, DATABASE_URL
5. **01-init.sql**: Same database setup

### Complete Java Example

1. **Dockerfile**: Uncomment Java sections
2. **grading_runner.py**:
   - Line 120: `test_command = f"mvn test -Dtest={','.join(self.test_files)}"`
   - Line 134: `xml_file = "target/surefire-reports/TEST-*.xml"`
   - Line 237: `build_command = "mvn package -DskipTests"`
   - Line 304: `migrate_cmd = None`
   - Line 321: `server_start_cmd = "java -jar target/app.jar"`

3. **setup.py**: Same as Node.js
4. **alter_env_files.py**: May not be needed; use application.properties instead
5. **01-init.sql**: Same database setup

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
docker build -t myproject-eval .
```

2. Run a test container:
```bash
docker run -it myproject-eval bash
```

3. Manually test each step:
```bash
# Check project is cloned
cd $PROJECT_DIR
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

## Getting Help

If you encounter issues:

1. Check all `[PLACEHOLDERS]` are replaced
2. Review technology-specific examples above
3. Test each component separately
4. Check logs for specific error messages
5. Refer to CUSTOMIZATION_GUIDE.md for more details

## Summary

The key customization points are:

1. **Dockerfile**: Project setup, dependencies, build
2. **grading_runner.py**: Test execution, build, migrations, server
3. **setup.py**: Project paths
4. **alter_env_files.py**: Environment configuration
5. **01-init.sql**: Database initialization

Everything else (Python framework code, tools, utilities) should work as-is without modification.

