#!/usr/bin/env python3
"""
Build, validate, run, push Docker images and generate metadata JSON
for the coding-template environment.

Actions (flags can be combined, e.g. -bvr):
  -b/--build:     Build Docker image (docker build -t <image> -f Dockerfile.hud .)
  -v/--validate:  Validate scenarios (baseline_fail + golden_pass, 0 agent steps)
  -r/--run:       Run an agent against scenarios
  -p/--push:      Push Docker image to registry
  -j/--json:      Generate problem-metadata.json

Execution order: build -> validate -> run -> push -> json

Parallelism uses asyncio throughout. Validation and run tasks for
different scenario IDs execute concurrently via asyncio.gather.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

import hud
from hud import Environment
from hud.agents.claude import ClaudeAgent

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PYPROJECT_PATH = Path("pyproject.toml")


# ============================================================================
# Image name resolution
# ============================================================================


def read_image_from_pyproject() -> str | None:
    """Read the image name from ``[tool.hud].image`` in pyproject.toml.

    Returns:
        The image name string, or None if not found.
    """
    if not PYPROJECT_PATH.exists():
        return None

    try:
        with open(PYPROJECT_PATH, "rb") as f:
            data = tomllib.load(f)
        return data.get("tool", {}).get("hud", {}).get("image")
    except Exception as exc:
        logger.debug(f"Failed to read pyproject.toml: {exc}")
        return None


def _looks_like_registry_image(image: str) -> bool:
    """Return True if the image name contains a registry prefix (has a '/')."""
    # Strip the tag/digest to inspect just the name portion
    name = image.split("@")[0].split(":")[0]
    return "/" in name


# ============================================================================
# Scenario discovery
# ============================================================================


def discover_scenario_ids() -> list[str]:
    """Auto-discover all registered scenario IDs by importing env.py.

    Importing ``env`` triggers ``import tasks`` at the bottom of env.py,
    which runs the ``@env.scenario(...)`` decorators and populates
    ``env._scenarios`` (a dict keyed by scenario name).
    """
    from env import env as _env  # noqa: WPS433 – intentional late import

    ids = list(_env._scenarios.keys())
    logger.info(f"Auto-discovered {len(ids)} scenario(s): {ids}")
    return ids


# ============================================================================
# Subprocess helpers (async)
# ============================================================================


async def run_subprocess(cmd: list[str], prefix: str) -> int:
    """Run a subprocess asynchronously, streaming output. Returns exit code."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    async for raw_line in process.stdout:
        line = raw_line.decode(errors="replace")
        sys.stdout.write(f"{prefix} {line}")
    await process.wait()
    return process.returncode or 0


# ============================================================================
# Build / Push
# ============================================================================


async def build_image(image: str) -> bool:
    """Build a single Docker image via ``docker build -t <image> -f Dockerfile.hud .``."""
    logger.info(f"Building image: {image}")
    cmd = ["docker", "build", "-t", image, "-f", "Dockerfile.hud", "."]
    rc = await run_subprocess(cmd, prefix="[build]")
    if rc != 0:
        logger.error(f"Build FAILED for {image} (exit code {rc})")
        return False
    logger.info(f"Build succeeded for {image}")
    return True


async def push_image(image: str) -> bool:
    """Push a single Docker image via ``docker push <image>``."""
    logger.info(f"Pushing image: {image}")
    cmd = ["docker", "push", image]
    rc = await run_subprocess(cmd, prefix="[push]")
    if rc != 0:
        logger.error(f"Push FAILED for {image} (exit code {rc})")
        return False
    logger.info(f"Push succeeded for {image}")
    return True


# ============================================================================
# Validate
# ============================================================================

VALIDATE_MODES = ("baseline_fail", "golden_pass")


async def validate_scenario(
    image: str,
    scenario_id: str,
    validate_mode: str,
    *,
    hints_enabled: bool = False,
) -> tuple[str, str, float | None]:
    """Validate a single scenario + mode by running an eval with 0 agent steps.

    Validation runs the scenario's setup and grading without any agent actions.
    For ``baseline_fail`` the grader inverts the score (baseline should fail tests),
    so the expected reward is 1.0 in both modes.

    Returns:
        (scenario_id, validate_mode, reward)  — reward is None on error.
    """
    label = f"{scenario_id} ({validate_mode})"
    logger.info(f"Validating: {label}")

    env = Environment("coding")
    env.connect_image(image)

    try:
        task = env(scenario_id, validate_mode=validate_mode, hints_enabled=hints_enabled)
        async with hud.eval(task, trace=True, quiet=True) as ctx:
            agent = ClaudeAgent.create(model="claude-sonnet-4-5")
            await agent.run(ctx, max_steps=0)
        reward = ctx.reward
    except Exception as exc:
        logger.error(f"Validation error for {label}: {exc}")
        return (scenario_id, validate_mode, None)

    return (scenario_id, validate_mode, reward)


async def validate_all(
    image: str,
    scenario_ids: list[str],
    *,
    hints_enabled: bool = False,
) -> tuple[list[str], list[str]]:
    """Validate all scenarios with both ``baseline_fail`` and ``golden_pass`` modes.

    Both modes are expected to yield ``reward == 1.0``.

    Returns:
        (passed_descriptions, failed_descriptions)
    """
    coros = [
        validate_scenario(image, sid, mode, hints_enabled=hints_enabled)
        for sid in scenario_ids
        for mode in VALIDATE_MODES
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    passed: list[str] = []
    failed: list[str] = []

    for result in results:
        if isinstance(result, BaseException):
            failed.append(f"Exception: {result}")
            continue

        sid, mode, reward = result
        desc = f"{sid} ({mode})"
        if reward == 1.0:
            logger.info(f"  PASS: {desc} -> reward={reward}")
            passed.append(desc)
        else:
            logger.error(f"  FAIL: {desc} -> reward={reward} (expected 1.0)")
            failed.append(desc)

    return passed, failed


# ============================================================================
# Run
# ============================================================================


async def run_scenario(
    image: str,
    scenario_id: str,
    max_steps: int,
    *,
    hints_enabled: bool = False,
) -> tuple[str, float | None]:
    """Run an agent against a scenario.

    Returns:
        (scenario_id, reward)  — reward is None on error.
    """
    logger.info(f"Running scenario: {scenario_id} (max_steps={max_steps}, hints={hints_enabled})")

    env = Environment("coding")
    env.connect_image(image)

    try:
        task = env(scenario_id, hints_enabled=hints_enabled)
        async with hud.eval(task, trace=True) as ctx:
            agent = ClaudeAgent.create(model="claude-sonnet-4-5")
            await agent.run(ctx, max_steps=max_steps)
        reward = ctx.reward
    except Exception as exc:
        logger.error(f"Run error for {scenario_id}: {exc}")
        return (scenario_id, None)

    return (scenario_id, reward)


async def run_all(
    image: str,
    scenario_ids: list[str],
    max_steps: int,
    *,
    hints_enabled: bool = False,
) -> tuple[list[tuple[str, float]], list[tuple[str, float | None]]]:
    """Run all scenarios concurrently with an agent.

    Returns:
        (succeeded, failed)  — each entry is (scenario_id, reward).
    """
    coros = [run_scenario(image, sid, max_steps, hints_enabled=hints_enabled) for sid in scenario_ids]
    results = await asyncio.gather(*coros, return_exceptions=True)

    succeeded: list[tuple[str, float]] = []
    failed: list[tuple[str, float | None]] = []

    for result in results:
        if isinstance(result, BaseException):
            failed.append((f"Exception: {result}", None))
            continue

        sid, reward = result
        if reward is not None and reward > 0:
            logger.info(f"  {sid} -> reward={reward}")
            succeeded.append((sid, reward))
        else:
            logger.error(f"  {sid} -> reward={reward}")
            failed.append((sid, reward))

    return succeeded, failed


# ============================================================================
# JSON generation
# ============================================================================


def _write_json(data: list[dict], path: str) -> None:
    """Write a JSON list to *path* with trailing newline."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def generate_json(
    image: str,
    scenario_ids: list[str],
    *,
    hints_enabled: bool = False,
    env_name: str = "coding-template",
) -> None:
    """Generate ``problem-metadata.json`` and ``remote_tasks.json``.

    - ``problem-metadata.json`` includes the Docker image name.
    - ``remote_tasks.json`` uses the deployed environment name (no image field)
      and is consumed by ``hud eval remote_tasks.json``.
    """
    scenario_args: dict = {}
    if hints_enabled:
        scenario_args["hints_enabled"] = True

    # -- problem-metadata.json (includes image) --
    problem_metadata = [
        {
            "env": {"name": env_name},
            "scenario": f"coding:{sid}",
            "image": image,
            "args": {**scenario_args},
        }
        for sid in scenario_ids
    ]
    _write_json(problem_metadata, "problem-metadata.json")
    logger.info(f"Generated problem-metadata.json with {len(problem_metadata)} scenario(s)")

    # -- remote_tasks.json (no image, used by hud eval) --
    remote_tasks = [
        {
            "env": {"name": env_name},
            "scenario": f"coding:{sid}",
            "args": {**scenario_args},
        }
        for sid in scenario_ids
    ]
    _write_json(remote_tasks, "remote_tasks.json")
    logger.info(f"Generated remote_tasks.json with {len(remote_tasks)} scenario(s)")


# ============================================================================
# Main
# ============================================================================


async def async_main(args: argparse.Namespace) -> int:
    """Execute the requested actions in order: build -> validate -> run -> push -> json."""
    # Resolve image name: CLI arg > [tool.hud].image in pyproject.toml
    image: str | None = args.image
    if not image:
        image = read_image_from_pyproject()
        if image:
            logger.info(f"Using image from pyproject.toml [tool.hud]: {image}")
        else:
            logger.error(
                "No image specified and could not read [tool.hud].image "
                "from pyproject.toml. Pass an image name or add:\n\n"
                "  [tool.hud]\n"
                '  image = "your-image:tag"\n\n'
                "to pyproject.toml."
            )
            return 1

    hints_enabled: bool = args.hints
    has_failures = False

    # Resolve scenario IDs: use --ids if given, otherwise auto-discover all.
    scenario_ids: list[str] = args.ids or []
    needs_scenarios = args.validate or args.run or args.json
    if not scenario_ids and needs_scenarios:
        scenario_ids = discover_scenario_ids()
        if not scenario_ids:
            logger.error("No scenarios found. Register scenarios via @env.scenario() in tasks/.")
            return 1

    if hints_enabled:
        logger.info("Hints ENABLED for this run")

    # --- Build ---
    if args.build:
        ok = await build_image(image)
        if not ok:
            return 1

    # --- Validate ---
    if args.validate:
        logger.info(
            f"Validating {len(scenario_ids)} scenario(s) "
            f"× {len(VALIDATE_MODES)} modes ..."
        )
        passed, failed = await validate_all(
            image, scenario_ids, hints_enabled=hints_enabled,
        )

        logger.info("")
        logger.info("Validation summary:")
        if passed:
            logger.info(f"  Passed ({len(passed)}): {', '.join(passed)}")
        if failed:
            logger.error(f"  Failed ({len(failed)}): {', '.join(failed)}")
            has_failures = True

    # --- Run ---
    if args.run:
        logger.info(
            f"Running {len(scenario_ids)} scenario(s) "
            f"(max_steps={args.max_steps}) ..."
        )
        succeeded, failed_runs = await run_all(
            image, scenario_ids, args.max_steps, hints_enabled=hints_enabled,
        )

        logger.info("")
        logger.info("Run summary:")
        if succeeded:
            logger.info(f"  Succeeded ({len(succeeded)}):")
            for sid, reward in succeeded:
                logger.info(f"    {sid}: reward={reward}")
        if failed_runs:
            logger.error(f"  Failed ({len(failed_runs)}):")
            for sid, reward in failed_runs:
                logger.error(f"    {sid}: reward={reward}")
            has_failures = True

    # --- Push ---
    if args.push:
        if not _looks_like_registry_image(image):
            logger.warning(
                f"Image name '{image}' does not contain a registry prefix "
                f"(e.g. 'myregistry.io/org/image:tag'). "
                f"Pushing a local-only name will likely fail."
            )
        ok = await push_image(image)
        if not ok:
            has_failures = True

    # --- JSON ---
    if args.json:
        generate_json(image, scenario_ids, hints_enabled=hints_enabled)

    return 1 if has_failures else 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build, validate, run, push, and generate JSON "
            "for coding-template Docker images."
        ),
    )

    parser.add_argument(
        "image",
        nargs="?",
        default=None,
        help=(
            "Docker image name (e.g. myregistry/coding-template:latest). "
            "If omitted, reads from [tool.hud].image in pyproject.toml."
        ),
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        help="Scenario IDs to validate / run (default: all registered scenarios)",
    )

    # Action flags --------------------------------------------------------
    parser.add_argument(
        "-b",
        "--build",
        action="store_true",
        help="Build Docker image (docker build -t <image> -f Dockerfile.hud .)",
    )
    parser.add_argument(
        "-p",
        "--push",
        action="store_true",
        help="Push image to registry",
    )
    parser.add_argument(
        "-v",
        "--validate",
        action="store_true",
        help="Validate scenarios (baseline_fail + golden_pass, 0 agent steps)",
    )
    parser.add_argument(
        "-r",
        "--run",
        action="store_true",
        help="Run agent against scenarios",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Generate problem-metadata.json",
    )

    # Options -------------------------------------------------------------
    parser.add_argument(
        "--hints",
        action="store_true",
        default=False,
        help="Enable hints for scenarios (passed as hints_enabled to scenarios, included in JSON args)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Max agent steps for --run (default: 20)",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    if not any([args.build, args.push, args.validate, args.run, args.json]):
        logger.warning(
            "No action flags provided (-b, -p, -v, -r, -j). Nothing to do."
        )
        return 0

    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
