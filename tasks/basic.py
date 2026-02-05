"""Basic difficulty tasks.

Each task is a scenario that handles its own setup and grading.
"""

from env import env, setup_task, make_prompt
from grading import AgentPatchGrader, Grade


@env.scenario("sample-json-bug")
async def sample_json_bug(hints_enabled: bool = False, validate_golden: bool = False):
    """Fix the JSON serialization bug in server.py."""
    
    setup_task(
        task_id="sample_json_bug",
        base="server_fix_baseline",
        test="server_fix_test",
        golden="server_fix_golden",
        validate_golden=validate_golden,
    )
    
    prompt = make_prompt("""Fix the JSON serialization bug in server.py.

The API server's responses are malformed. When you make a request to any endpoint,
the response body is not valid JSON - it looks like a Python dict representation
instead of proper JSON (e.g., single quotes instead of double quotes).
""")
    
    _ = yield prompt
    
    # Grade using AgentPatchGrader
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="sample_json_bug",
            test_files=["test_server.py"],
            # Uses default pytest command
        )
    ])
    
    yield grade.score


# ==============================================================================
# TEMPLATE: Add your tasks below
# ==============================================================================
#
# @env.scenario("my-task")
# async def my_task(hints_enabled: bool = False):
#     """Task description."""
#     
#     setup_task(
#         task_id="my_task",
#         base="my_task_baseline",
#         test="my_task_test",
#         golden="my_task_golden",
#     )
#     
#     prompt = make_prompt("Fix the bug in foo.py...")
#     _ = yield prompt
#     
#     grade = Grade.from_subscores([
#         AgentPatchGrader.grade(
#             weight=1.0,
#             problem_id="my_task",
#             test_files=["test_foo.py"],
#             # For custom test frameworks:
#             # test_command="yarn test {test_files}",
#             # results_xml="jest_results.xml",
#             # build_command="yarn build",
#         )
#     ])
#     yield grade.score
