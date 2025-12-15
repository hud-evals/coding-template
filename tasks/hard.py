import logging

from grading import AgentPatchGrader, EnvironmentState, Grade, HintSpec, problem

logger = logging.getLogger(__name__)


# ==============================================================================
# TEMPLATE: Hard Difficulty Tasks
# ==============================================================================
# This file contains example templates for hard difficulty coding tasks.
# Hard tasks typically involve:
# - Complex multi-file changes
# - Deep system integration
# - Architectural decisions
# - Understanding complex business logic
# - Multiple interconnected components
# ==============================================================================


@problem(
    id="example_hard_task",
    description="""
    Example Task: Implement [complex feature] with [multiple components]
    
    [Comprehensive description of the task]:
    - Current behavior: [what happens now across the system]
    - Expected behavior: [what should happen with new feature]
    
    Example: "Implement time-based failure rate analysis for webhook subscriptions.
    Replace the simple '25 consecutive failures' check with a sophisticated system
    that tracks failures over a time window, calculates failure rates, and makes
    intelligent disabling decisions based on statistical thresholds."
    """,
    hints=[
#         HintSpec(
#             hint_type="legit/leaky",
#             text="Consider how you'll query data efficiently for the time window",
#             why_legitmate="Prompts thinking about approach without revealing specifics",
#         ),
#        ... (add more hints as needed)
    ],
    difficulty="hard",
    task_type="coding",
    review_level="no-review",
    base="example_hard_task_baseline",
    test="example_hard_task_test",
    golden="example_hard_task_golden",
)
def example_hard_task(state: EnvironmentState) -> Grade:
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
                base="example_hard_task_baseline",
                test="example_hard_task_test",
                golden="example_hard_task_golden",
                test_files=[
                    "path/to/test/file",
                ],
            )
        ]
    )

# ==============================================================================
# TASK TEMPLATE STRUCTURE FOR HARD TASKS
# ==============================================================================
#
# When creating a new hard task, follow this structure:
#
# 1. Problem Decorator:
#    - id: Unique identifier (lowercase, underscores)
#    - description: Comprehensive explanation of complex multi-component task
#    - hints: List of HintSpec objects (optional, often helpful for hard tasks)
#    - difficulty: "hard"
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
#    - Specify test files to run (often multiple files)
#    - Can include multiple graders for different components
#
# Hard Task Characteristics:
# - Involves 4+ files or complex architectural changes
# - Requires deep system understanding
# - Multiple interconnected components
# - ~2+ hours of work
#
# ==============================================================================
