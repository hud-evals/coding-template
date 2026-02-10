"""Basic difficulty tasks.

Each task is a scenario that handles its own setup and grading.

In the git-enabled template, the agent has full git access. The setup_task()
function just checks out the starting branch — patches were pre-extracted
at Docker build time.
"""

from env import env, setup_task, make_prompt
from grading import AgentPatchGrader, Grade, ValidateMode


@env.scenario("sample-json-bug")
async def sample_json_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the JSON serialization bug in server.py."""

    # In the git-enabled template, setup_task only needs:
    #   task_id: matches the key in task_config.yaml
    #   checkout: the branch the agent starts on
    # Patches (test.patch, golden.patch) are pre-extracted at build time.
    setup_task(
        task_id="sample-json-bug",
        checkout="server_fix_baseline",
        validate_mode=validate_mode,
    )

    prompt = make_prompt("""Fix the JSON serialization bug in server.py.

The API server's responses are malformed. When you make a request to any endpoint,
the response body is not valid JSON - it looks like a Python dict representation
instead of proper JSON (e.g., single quotes instead of double quotes).

Hint: use git log and git blame to investigate when the bug was introduced.
""")

    _ = yield prompt

    # Grade using AgentPatchGrader
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="sample-json-bug",
            test_files=["test_server.py"],
            validate_mode=validate_mode,
            # Uses default pytest command
        )
    ])

    yield grade.score


# ==============================================================================
# TEMPLATE: Add your tasks below
# ==============================================================================
#
# @env.scenario("my-task")
# async def my_task(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
#     """Task description."""
#
#     setup_task(
#         task_id="my-task",         # Must match key in task_config.yaml
#         checkout="my_baseline",     # Branch the agent starts on
#         validate_mode=validate_mode,
#     )
#
#     prompt = make_prompt("Fix the bug in foo.py...")
#     _ = yield prompt
#
#     grade = Grade.from_subscores([
#         AgentPatchGrader.grade(
#             weight=1.0,
#             problem_id="my-task",
#             test_files=["test_foo.py"],
#             validate_mode=validate_mode,
#             # For custom test frameworks:
#             # test_command="yarn test {test_files}",
#         )
#     ])
#     yield grade.score
