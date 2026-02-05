"""Medium difficulty tasks.

Each task is a scenario that handles its own setup and grading.
"""

# from env import env, setup_task, make_prompt
# from grading import AgentPatchGrader, Grade


# ==============================================================================
# TEMPLATE: Medium Difficulty Tasks
# ==============================================================================
# Medium tasks typically involve:
# - Multi-file changes (2-4 files)
# - Moderate system understanding required
# - Integration between components
# ==============================================================================


# @env.scenario("my-medium-task")
# async def my_medium_task(hints_enabled: bool = False):
#     """Implement feature X across multiple components."""
#     
#     setup_task(
#         task_id="my_medium_task",
#         base="my_medium_task_baseline",
#         test="my_medium_task_test",
#         golden="my_medium_task_golden",
#     )
#     
#     prompt = make_prompt("""Implement feature X.
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
#             base="my_medium_task_baseline",
#             test="my_medium_task_test",
#             golden="my_medium_task_golden",
#             test_files=["test_feature_x.py"],
#         )
#     ])
#     
#     yield grade.score
