import logging

from hud_controller.graders import AgentPatchGrader
from hud_controller.spec import EnvironmentState, Grade, problem

logger = logging.getLogger(__name__)


# ==============================================================================
# TEMPLATE: Easy Difficulty Tasks
# ==============================================================================
# This file contains example templates for easy difficulty coding tasks.
# Easy tasks typically involve:
# - Simple bug fixes
# - Straightforward feature additions
# - Clear, well-defined changes to 1-2 files
# - Minimal context required
# ==============================================================================


@problem(
    id="example_easy_task",
    description="""
    Example Task 1: Fix a simple bug in [component name]
    
    [Detailed description of the bug]:
    - Current behavior: [what happens now]
    - Expected behavior: [what should happen]
    
    Example: "Fix the button click handler in components/Button.tsx that doesn't 
    trigger the onClick callback. The issue is in the event handler binding."
    """,
    hints=[
#         HintSpec(
#             hint_type="legit/leaky",
#             text="The issue is in the event handler lifecycle",
#             why_legitmate="Points to general area without revealing solution"
#         ),
#        ... (add more hints as needed)
    ],
    difficulty="easy",
    task_type="coding",
    review_level="no-review",
    base="example_easy_task_baseline",
    test="example_easy_task_test",
    golden="example_easy_task_golden",
)
def example_easy_task(state: EnvironmentState) -> Grade:
    """
    Task: [Brief one-line description]
    
    :param state (EnvironmentState): The current state of the environment
                                    after the agent has worked on the task

    Returns:
        Grade: A grade object containing the score (0.0 to 1.0) based on whether
               the [specific requirement] is met and tests pass.

    Grading:
        - Full score (1.0): If [specific success criteria] and all tests pass
        - Zero score (0.0): If [specific failure criteria] or tests fail
    """
    return Grade.from_subscores(
        [
            AgentPatchGrader.grade(
                state=state,
                weight=1.0,
                base="example_easy_task_baseline",
                test="example_easy_task_test",
                golden="example_easy_task_golden",
                test_files=[
                    "path/to/test/file",
                ],
            )
        ]
    )


# ==============================================================================
# TASK TEMPLATE STRUCTURE
# ==============================================================================
#
# When creating a new easy task, follow this structure:
#
# 1. Problem Decorator:
#    - id: Unique identifier (lowercase, underscores)
#    - description: High level explanation of the task
#    - hints: List of HintSpec objects (optional)
#    - difficulty: "easy"
#    - task_type: "coding"
#    - review_level: Review status
#    - base: Git branch/tag for baseline code
#    - test: Git branch/tag with tests
#    - golden: Git branch/tag with correct solution
#
# 2. Function Definition:
#    - Name should match the problem id
#    - Takes EnvironmentState as parameter
#    - Returns Grade object
#
# 3. Docstring:
#    - Brief task description
#    - Parameter explanation
#    - Return value description
#    - Grading criteria (1.0 vs 0.0)
#
# 4. Grade Composition:
#    - Use Grade.from_subscores()
#    - Include AgentPatchGrader with appropriate weight
#    - Specify test files to run
#    - Can include multiple graders with different weights
#
# ==============================================================================


# ==============================================================================
# EXAMPLE WITH HINTS
# ==============================================================================
#
# For tasks that benefit from hints, use the HintSpec class:
#
# from hud_controller.spec import HintSpec
#
# @problem(
#     id="example_with_hints",
#     description="...",
#     hints=[
#         HintSpec(
#             hint_type="legit",
#             text="The issue is in the event handler lifecycle",
#             why_legitmate="Points to general area without revealing solution"
#         ),
#         HintSpec(
#             hint_type="leaky",
#             text="You need to add useCallback hook",
#             why_legitmate="Gives away specific implementation detail"
#         ),
#     ],
#     difficulty="easy",
#     # ... rest of config
# )
#
# ==============================================================================
