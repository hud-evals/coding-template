import logging

from environment.graders import AgentPatchGrader
from server.spec import EnvironmentState, Grade, HintSpec, problem

logger = logging.getLogger(__name__)


# ==============================================================================
# TEMPLATE: Medium Difficulty Tasks
# ==============================================================================
# This file contains example templates for medium difficulty coding tasks.
# Medium tasks typically involve:
# - Multi-file changes (2-4 files)
# - Moderate system understanding required
# - Some architectural awareness needed
# - Integration between components
# - More complex logic than easy tasks
# ==============================================================================


@problem(
    id="example_medium_task",
    description="""
    Example Task: Implement [feature] across [multiple components]
    
    [Detailed description of the task]:
    - Current behavior: [what happens now across components]
    - Expected behavior: [what should happen]
    
    Example: "Implement automatic subscription management when groups are added
    to documents. Update the processor to handle group events, create a new task
    for individual subscriptions, and ensure proper batch processing."
    """,
    hints=[
#         HintSpec(
#             hint_type="legit/leaky",
#             text="Consider how to process large groups efficiently",
#             why_legitmate="Prompts thinking about performance without revealing solution",
#         ),
#        ... (add more hints as needed)
    ],
    difficulty="medium",
    task_type="coding",
    review_level="no-review",
    base="example_medium_task_baseline",
    test="example_medium_task_test",
    golden="example_medium_task_golden",
)
def example_medium_task(state: EnvironmentState) -> Grade:
    """
    Task: [Brief one-line description]
    
    :param state (EnvironmentState): The current state of the environment
                                    after the agent has worked on the task

    Returns:
        Grade: A grade object containing the score (0.0 to 1.0) based on whether
               the feature is properly implemented.

    Grading:
        - Full score (1.0): If feature implemented correctly and tests pass
        - Zero score (0.0): If implementation is incorrect or tests fail
    """
    return Grade.from_subscores(
        [
            AgentPatchGrader.grade(
                state=state,
                weight=1.0,
                base="example_medium_task_baseline",
                test="example_medium_task_test",
                golden="example_medium_task_golden",
                test_files=[
                    "path/to/test/file",
                ],
            )
        ]
    )


# ==============================================================================
# TASK TEMPLATE STRUCTURE FOR MEDIUM TASKS
# ==============================================================================
#
# When creating a new medium task, follow this structure:
#
# 1. Problem Decorator:
#    - id: Unique identifier (lowercase, underscores)
#    - description: Detailed explanation of task across multiple components
#    - hints: List of HintSpec objects (optional, usually 0-2 hints)
#    - difficulty: "medium"
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
#    - Specify test files to run (typically 1-3 files)
#    - Can include multiple graders with different weights for partial credit
#
# Medium Task Characteristics:
# - Involves 2-4 files
# - Requires integration between components
# - More complex than easy tasks, simpler than hard tasks
# - ~1 hour of work
#
# ==============================================================================
