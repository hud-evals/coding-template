# Template Verification Checklist

Use this checklist to verify the template is properly configured and ready for use.

## Pre-Delivery Verification

### ✅ Documentation Complete

- [x] README.md exists and is comprehensive
- [x] SETUP_GUIDE.md provides detailed setup instructions
- [x] CUSTOMIZATION_GUIDE.md explains how to adapt the template
- [x] QUICKSTART.md offers a quick 15-minute getting started guide
- [x] TEMPLATE_SUMMARY.md summarizes what was done
- [x] VERIFICATION_CHECKLIST.md (this file) exists

### ✅ Template Files Created

- [x] basic_tasks.py converted to generic templates
- [x] medium_tasks.py converted to generic templates  
- [x] hard_tasks.py converted to generic templates
- [x] All templates include comprehensive comments
- [x] Examples show different patterns (hints, multi-grader, etc.)

### ✅ Code Generalized

- [x] No hardcoded project-specific paths
- [x] Repository path configurable via REPO_PATH env var
- [x] Database name configurable via TEST_DB_NAME env var
- [x] All project-specific references removed or made configurable
- [x] Dependencies properly specified in pyproject.toml

### ✅ Framework Intact

- [x] Core grading logic unchanged
- [x] Test execution framework works
- [x] Grade composition system functional
- [x] MCP server integration intact
- [x] All tools implemented and working

## Post-Customization Verification

Use this section after customizing the template for a specific project.

### Environment Setup

- [ ] Virtual environment created: `python -m venv venv`
- [ ] Dependencies installed: `pip install -e .`
- [ ] Environment variables configured:
  - [ ] REPO_PATH set to target repository
  - [ ] TEST_DB_NAME set (if using database)
  - [ ] MCP_TESTING_MODE set to "1"
  - [ ] Any other project-specific variables

### Repository Configuration

- [ ] Target repository accessible at REPO_PATH
- [ ] Repository has git branches for at least one task:
  - [ ] baseline branch exists and builds
  - [ ] test branch exists with failing tests
  - [ ] golden branch exists with passing tests
- [ ] Test framework configured:
  - [ ] Jest config includes junit reporter (if using Jest)
  - [ ] pytest config includes junit output (if using pytest)
  - [ ] Other test framework properly configured

### Build System

- [ ] Build command identified and documented
- [ ] Build command works in target repository
- [ ] grading_runner.py updated with correct build command
- [ ] Build cleanup steps adapted (if needed)
- [ ] Build succeeds on baseline branch
- [ ] Build succeeds on test branch
- [ ] Build succeeds on golden branch

### Database (if applicable)

- [ ] Database server running and accessible
- [ ] Test database can be created/dropped
- [ ] Migration command works
- [ ] Database reset logic tested
- [ ] OR: Database setup removed if not needed

### Server Management (if applicable)

- [ ] Server start command identified
- [ ] Server starts successfully
- [ ] Server responds on expected port
- [ ] _needs_server_start() logic appropriate
- [ ] Server cleanup works properly
- [ ] OR: Server management disabled if not needed

### Test Execution

- [ ] Test command works manually in repository
- [ ] Tests produce JUnit XML output
- [ ] XML output location correctly configured
- [ ] Test results parsed correctly
- [ ] Failed tests produce score 0.0
- [ ] Passing tests produce score 1.0

### Task Creation

- [ ] At least one task defined
- [ ] Task id is unique
- [ ] Task description is clear
- [ ] Branch names match git branches
- [ ] Test files specified correctly
- [ ] Task difficulty appropriate
- [ ] Task registered in PROBLEM_REGISTRY

### Grading Workflow

- [ ] Task can be graded: `grade_problem task_id`
- [ ] Repository copied to temporary workspace
- [ ] Test patch applies cleanly
- [ ] Build succeeds after test patch
- [ ] Tests fail with only test patch (score 0.0)
- [ ] Golden patch applies cleanly
- [ ] Tests pass with golden patch (score 1.0)
- [ ] Cleanup happens after grading
- [ ] JUnit XML generated
- [ ] Score computed correctly

## Code Quality Checks

### Linting

- [ ] No linting errors in modified files
- [ ] Code follows project style guide
- [ ] All imports resolve correctly
- [ ] No unused variables or imports

### Structure

- [ ] Clear separation between framework and customization
- [ ] Configuration values not hardcoded
- [ ] Logging statements appropriate
- [ ] Error handling adequate
- [ ] Comments explain non-obvious logic

### Documentation

- [ ] All custom code documented
- [ ] Environment variables documented
- [ ] Configuration options explained
- [ ] Examples provided where helpful
- [ ] Troubleshooting section added

## Integration Tests

### Basic Workflow

```bash
# Run these commands to verify basic functionality

# 1. Installation works
pip install -e .

# 2. Registration works
python -c "from hud_controller.spec import PROBLEM_REGISTRY; print(len(PROBLEM_REGISTRY))"

# 3. Task can be accessed
python -c "from hud_controller.spec import PROBLEM_REGISTRY; print(PROBLEM_REGISTRY[0].id)"

# 4. Grading can be initiated
grade_problem <your_task_id>
```

Results:
- [ ] Installation succeeded
- [ ] Tasks registered correctly
- [ ] Task accessible
- [ ] Grading initiated (check logs even if it fails)

### Full Grading Run

```bash
# Run complete grading workflow
export REPO_PATH=/path/to/repo
export TEST_DB_NAME=test_db
export LOG_LEVEL=DEBUG

grade_problem <your_task_id> 2>&1 | tee full_test.log
```

Check log for:
- [ ] "Copying original repo" message
- [ ] "Applying test patch" message
- [ ] "Compiling project" message
- [ ] "Running tests" message (or equivalent)
- [ ] JUnit XML parsing
- [ ] Final score output

Results:
- [ ] All steps completed
- [ ] Score computed (0.0 or 1.0)
- [ ] No unexpected errors

## Client Delivery Checklist

### Documentation Package

- [ ] README.md reviewed and accurate
- [ ] SETUP_GUIDE.md reviewed and complete
- [ ] CUSTOMIZATION_GUIDE.md reviewed and helpful
- [ ] QUICKSTART.md tested and working
- [ ] TEMPLATE_SUMMARY.md explains what was done
- [ ] VERIFICATION_CHECKLIST.md included
- [ ] PROJECT_SPECIFIC.md created (optional, for customized versions)

### Code Package

- [ ] All Python files present
- [ ] pyproject.toml complete with dependencies
- [ ] Dockerfile included (if using Docker)
- [ ] .dockerignore appropriate
- [ ] Support scripts included
- [ ] No sensitive data in code
- [ ] No development artifacts (.pyc, __pycache__, etc.)

### Examples and Templates

- [ ] Template tasks in extractors/ are clear examples
- [ ] At least 3 templates per difficulty level
- [ ] Comments explain all sections
- [ ] Different patterns demonstrated
- [ ] Easy to copy and adapt

### Testing Evidence

- [ ] Verification checklist completed
- [ ] At least one task successfully graded
- [ ] Example grading logs available
- [ ] Common issues documented
- [ ] Troubleshooting guide tested

## Sign-Off

### Template Creator

- [ ] All checklist items reviewed
- [ ] Code tested end-to-end
- [ ] Documentation proofread
- [ ] Examples verified
- [ ] Ready for delivery

**Name:** _________________  
**Date:** _________________  
**Notes:** _________________

### Client/Recipient

- [ ] Documentation received and reviewed
- [ ] Installation successful
- [ ] First task created and tested
- [ ] Questions answered
- [ ] Ready to use independently

**Name:** _________________  
**Date:** _________________  
**Notes:** _________________

## Post-Delivery Support

### Training Completed

- [ ] Walkthrough of QUICKSTART.md
- [ ] Live demonstration of creating a task
- [ ] Live demonstration of running grading
- [ ] Troubleshooting common issues shown
- [ ] Questions answered

### Handoff Documentation

- [ ] Contact information for support
- [ ] Expected response times
- [ ] Escalation procedure
- [ ] Additional resources provided

## Notes and Observations

Use this space to document any issues found or improvements needed:

```
[Add notes here]

Example:
- Build time is slow, consider caching dependencies
- Tests timeout on large codebases, may need to increase timeout
- Database setup takes 30 seconds, could be optimized
```

## Recommended Next Steps

After verifying the template:

1. **Immediate (Day 1)**
   - [ ] Create 2-3 simple tasks
   - [ ] Test grading workflow
   - [ ] Document any issues

2. **Short Term (Week 1)**
   - [ ] Create tasks across all difficulty levels
   - [ ] Establish task creation process
   - [ ] Set up version control for tasks
   - [ ] Create internal documentation

3. **Medium Term (Month 1)**
   - [ ] Build comprehensive task suite
   - [ ] Integrate with CI/CD (if applicable)
   - [ ] Gather feedback from users
   - [ ] Refine grading criteria

4. **Long Term (Ongoing)**
   - [ ] Maintain and update tasks
   - [ ] Track agent performance over time
   - [ ] Improve difficult/ambiguous tasks
   - [ ] Share learnings with team

---

**Template Version:** 1.0  
**Last Updated:** October 28, 2025  
**Status:** ✅ Ready for Use

