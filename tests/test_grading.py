"""Grading validation tests for all tasks (HUD v6).

Each task's grading pipeline runs inside the served environment (a built Docker
image by default), with **no agent edits**:
  - baseline (buggy) code fails the hidden tests  -> grader returns 1.0 (inverted)
  - golden (fixed) code passes the hidden tests    -> grader returns 1.0

``setup_task`` runs when the task starts (checks out baseline/golden, generates
patches); the grader applies the hidden ``test.patch`` and runs pytest when the
``Run`` context exits. The agent never acts, so the deliverable is purely the
checked-out state.

Usage:
    uv run pytest tests/test_grading.py -v --image coding-template:dev
    uv run pytest tests/test_grading.py -v --url tcp://127.0.0.1:8765
    uv run pytest tests/test_grading.py -v -k sample-json-bug --image ...
"""

import pytest
from hud import Run, connect

from tasks import tasks as ALL_TASKS

pytestmark = pytest.mark.asyncio(loop_scope="session")

BY_SLUG = {t.slug: t for t in ALL_TASKS}

# Non-hint tasks to validate (hint variants share the same branches/grading).
TASK_SLUGS = [
    "sentry-fix",
    "notif-bug",
    "settings-v2",
    "webhook-bug",
]


async def _grade(runtime, slug: str, validate_mode: str) -> float:
    """Start the task with a validate_mode, run no agent, return the reward."""
    base = BY_SLUG[slug]
    task = base.model_copy(update={"args": {**base.args, "validate_mode": validate_mode}})

    async with runtime(task) as addr, connect(addr) as client:
        async with Run(client, task.id, task.args) as run:
            pass  # no agent work: setup runs on start, grading on exit
    return run.reward


@pytest.mark.parametrize("slug", TASK_SLUGS)
async def test_baseline_fails(runtime, slug):
    """Baseline (buggy) code should fail the tests -> grader returns 1.0 (inverted)."""
    reward = await _grade(runtime, slug, "baseline_fail")
    assert reward == 1.0, (
        f"{slug}: baseline should fail tests (inverted score should be 1.0, got {reward})"
    )


@pytest.mark.parametrize("slug", TASK_SLUGS)
async def test_golden_passes(runtime, slug):
    """Golden (fixed) code should pass the tests -> grader returns 1.0."""
    reward = await _grade(runtime, slug, "golden_pass")
    assert reward == 1.0, (
        f"{slug}: golden branch should pass tests (score should be 1.0, got {reward})"
    )
