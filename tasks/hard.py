"""Hard difficulty tasks.

Each task is a scenario that handles its own setup and grading.
"""

# from env import env, setup_task, make_prompt
# from grading import AgentPatchGrader, Grade, ValidateMode


# ==============================================================================
# TEMPLATE: Hard Difficulty Tasks
# ==============================================================================
# Hard tasks typically involve:
# - Complex multi-file changes (4+ files)
# - Deep system integration
# - Architectural decisions
# ==============================================================================


# @env.scenario("my-hard-task")
# async def my_hard_task(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
#     """Implement complex feature Y with architectural changes."""
#     
#     setup_task(
#         task_id="my_hard_task",
#         base="my_hard_task_baseline",
#         test="my_hard_task_test",
#         golden="my_hard_task_golden",
#         validate_mode=validate_mode,
#     )
#     
#     prompt = make_prompt("""Implement complex feature Y.
#
# Current behavior: ...
# Expected behavior: ...
# """)
#     
#     _ = yield prompt
#     
#     grade = Grade.from_subscores([
#         AgentPatchGrader.grade(
#             weight=1.0,
#             problem_id="my_hard_task",
#             test_files=["test_feature_y.py", "test_integration.py"],
#             validate_mode=validate_mode,
#         )
#     ])
#     
#     yield grade.score
