"""Grading validation tests for all scenarios.

These tests run each scenario's grading pipeline inside the Docker container,
verifying that:
  - The baseline (buggy) code fails the tests  → score 0.0
  - The golden (fixed) code passes the tests   → score 1.0

Usage:
    uv run pytest tests/test_grading.py -v
    uv run pytest tests/test_grading.py -v --image my-image:latest
    uv run pytest tests/test_grading.py -v -k server_fix
"""

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Each entry: (scenario_slug, problem_id)
SCENARIOS = [
    ("sample-json-bug", "sample_json_bug"),
    ("sentry-fix", "sentry_fix"),
    ("settings-bug", "settings_bug"),
    ("notif-bug", "notif_bug"),
    ("order-bug", "order_bug"),
    ("settings-v2", "settings_v2"),
    ("webhook-bug", "webhook_bug"),
]


def _env_name(env) -> str:
    """Get the environment name for prompt/resource addressing."""
    return env.name


def _extract_score(resource_content) -> float:
    """Extract numeric score from a resource read result.

    The resource returns JSON like: {"reward": 1.0, "done": true, "info": {}, "isError": false}
    """
    text = None
    if isinstance(resource_content, list):
        for block in resource_content:
            if hasattr(block, "text"):
                text = block.text
                break
    else:
        text = str(resource_content)

    if text is None:
        raise ValueError(f"No text content in resource result: {resource_content}")

    # Try JSON first (e.g. {"reward": 1.0, ...}), fall back to bare float
    try:
        data = json.loads(text)
        return float(data["reward"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return float(text)


@pytest.mark.parametrize("scenario_slug,problem_id", SCENARIOS, ids=[s[1] for s in SCENARIOS])
async def test_baseline_fails(env, scenario_slug, problem_id):
    """Baseline (buggy) code should fail the test suite → grader returns 1.0 (inverted)."""
    name = _env_name(env)
    prompt_name = f"{name}:{scenario_slug}"

    # Setup phase: checkout baseline, generate patches
    await env.get_prompt(prompt_name, {"validate_mode": "baseline_fail"})

    # Evaluate phase: apply test.patch, run tests, grade
    result = await env.read_resource(prompt_name)
    score = _extract_score(result)

    # baseline_fail mode inverts the score: if tests fail (expected) → score 1.0
    assert score == 1.0, f"{problem_id}: baseline should fail tests (inverted score should be 1.0, got {score})"


@pytest.mark.parametrize("scenario_slug,problem_id", SCENARIOS, ids=[s[1] for s in SCENARIOS])
async def test_golden_passes(env, scenario_slug, problem_id):
    """Golden (fixed) code should pass the test suite → grader returns 1.0."""
    name = _env_name(env)
    prompt_name = f"{name}:{scenario_slug}"

    # Setup phase: checkout golden branch, generate patches
    await env.get_prompt(prompt_name, {"validate_mode": "golden_pass"})

    # Evaluate phase: apply test.patch, run tests, grade
    result = await env.read_resource(prompt_name)
    score = _extract_score(result)

    assert score == 1.0, f"{problem_id}: golden branch should pass tests (score should be 1.0, got {score})"
