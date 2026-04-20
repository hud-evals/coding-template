#!/usr/bin/env python3
"""
Build, validate, run, push Docker images and generate metadata JSON
for the coding-template environment.

Actions:
  -b/--build:     Build Docker image (docker build -t <image> -f Dockerfile.hud .)
  -v/--validate:  Validate tasks (baseline_fail + golden_pass, 0 agent steps)
  -r/--run:       Run an agent against tasks
  -p/--push:      Push Docker image to registry
  -j/--json:      Generate problem-metadata.json

-b and -v/-r are mutually exclusive. Extra args after -- are forwarded
to the active action:

  Build with extra docker build args:
    uv run imagectl4.py -b -- --no-cache --build-arg REPO_URL=https://...

  Validate with extra docker run args:
    uv run imagectl4.py -v -- -e MY_VAR=value -v /host/path:/ctr/path

-p and -j can be combined with either side.

Parallelism uses asyncio throughout. Validation and run for
different tasks execute concurrently via asyncio.gather.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import hud
from hud import Environment
from hud.agents.claude import ClaudeAgent

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PYPROJECT_PATH = Path("pyproject.toml")

SCENARIO_NAME = "coding-bug"


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
# Task discovery
# ============================================================================


def discover_tasks() -> dict[str, dict[str, Any]]:
    """Auto-discover all registered tasks by importing tasks.py.

    Returns a dict mapping task name to its bound scenario args.
    Each task is a ``.task()`` call on the ``coding_bug`` scenario with
    all content passed as parameters (task_id, description, branches, etc.).
    """
    from tasks import tasks as _tasks  # noqa: WPS433 – intentional late import

    result = {}
    for task_name, task_obj in _tasks.items():
        result[task_name] = task_obj.args or {}
    logger.info(f"Auto-discovered {len(result)} task(s): {list(result.keys())}")
    return result


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


async def build_image(image: str, *, extra_args: list[str] | None = None) -> bool:
    """Build a single Docker image via ``docker build -t <image> -f Dockerfile.hud .``."""
    logger.info(f"Building image: {image}")
    cmd = ["docker", "build", "-t", image, "-f", "Dockerfile.hud"]
    cmd.extend(extra_args or [])
    github_token = os.environ.get("CODING_GITHUB_TOKEN")
    if github_token:
        cmd.extend(["--secret", "id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN"])
    cmd.append(".")
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


async def validate_task(
    image: str,
    task_name: str,
    task_args: dict[str, Any],
    validate_mode: str,
    *,
    docker_args: list[str] | None = None,
) -> tuple[str, str, float | None]:
    """Validate a single task + mode by running an eval with 0 agent steps.

    Validation runs the scenario's setup and grading without any agent actions.
    For ``baseline_fail`` the grader inverts the score (baseline should fail tests),
    so the expected reward is 1.0 in both modes.

    Returns:
        (task_name, validate_mode, reward)  — reward is None on error.
    """
    label = f"{task_name} ({validate_mode})"
    logger.info(f"Validating: {label}")

    env = Environment("coding")
    env.connect_image(image, docker_args=docker_args)

    try:
        task = env(SCENARIO_NAME, validate_mode=validate_mode, **task_args)
        async with hud.eval(task, trace=True, quiet=True) as ctx:
            agent = ClaudeAgent.create(model="claude-sonnet-4-5")
            await agent.run(ctx, max_steps=0)
        reward = ctx.reward
    except Exception as exc:
        logger.error(f"Validation error for {label}: {exc}")
        return (task_name, validate_mode, None)

    return (task_name, validate_mode, reward)


async def validate_all(
    image: str,
    task_registry: dict[str, dict[str, Any]],
    *,
    docker_args: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate all tasks with both ``baseline_fail`` and ``golden_pass`` modes.

    Both modes are expected to yield ``reward == 1.0``.

    Returns:
        (passed_descriptions, failed_descriptions)
    """
    coros = [
        validate_task(image, name, args, mode, docker_args=docker_args)
        for name, args in task_registry.items()
        for mode in VALIDATE_MODES
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    passed: list[str] = []
    failed: list[str] = []

    for result in results:
        if isinstance(result, BaseException):
            failed.append(f"Exception: {result}")
            continue

        name, mode, reward = result
        desc = f"{name} ({mode})"
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


async def run_task(
    image: str,
    task_name: str,
    task_args: dict[str, Any],
    max_steps: int,
    *,
    docker_args: list[str] | None = None,
) -> tuple[str, float | None]:
    """Run an agent against a task.

    Returns:
        (task_name, reward)  — reward is None on error.
    """
    logger.info(f"Running task: {task_name} (max_steps={max_steps})")

    env = Environment("coding")
    env.connect_image(image, docker_args=docker_args)

    try:
        task = env(SCENARIO_NAME, **task_args)
        async with hud.eval(task, trace=True) as ctx:
            agent = ClaudeAgent.create(model="claude-sonnet-4-5")
            await agent.run(ctx, max_steps=max_steps)
        reward = ctx.reward
    except Exception as exc:
        logger.error(f"Run error for {task_name}: {exc}")
        return (task_name, None)

    return (task_name, reward)


async def run_all(
    image: str,
    task_registry: dict[str, dict[str, Any]],
    max_steps: int,
    *,
    docker_args: list[str] | None = None,
) -> tuple[list[tuple[str, float]], list[tuple[str, float | None]]]:
    """Run all tasks concurrently with an agent.

    Returns:
        (succeeded, failed)  — each entry is (task_name, reward).
    """
    coros = [run_task(image, name, args, max_steps, docker_args=docker_args) for name, args in task_registry.items()]
    results = await asyncio.gather(*coros, return_exceptions=True)

    succeeded: list[tuple[str, float]] = []
    failed: list[tuple[str, float | None]] = []

    for result in results:
        if isinstance(result, BaseException):
            failed.append((f"Exception: {result}", None))
            continue

        name, reward = result
        if reward is not None and reward > 0:
            logger.info(f"  {name} -> reward={reward}")
            succeeded.append((name, reward))
        else:
            logger.error(f"  {name} -> reward={reward}")
            failed.append((name, reward))

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
    task_registry: dict[str, dict[str, Any]],
    *,
    env_name: str = "coding-template",
) -> None:
    """Generate ``problem-metadata.json`` and ``remote_tasks.json``.

    - ``problem-metadata.json`` includes the Docker image name.
    - ``remote_tasks.json`` uses the deployed environment name (no image field)
      and is consumed by ``hud eval remote_tasks.json``.
    """
    # -- problem-metadata.json (includes image) --
    problem_metadata = [
        {
            "env": {"name": env_name},
            "scenario": f"coding:{SCENARIO_NAME}",
            "image": image,
            "args": {**args},
        }
        for args in task_registry.values()
    ]
    _write_json(problem_metadata, "problem-metadata.json")
    logger.info(f"Generated problem-metadata.json with {len(problem_metadata)} task(s)")

    # -- remote_tasks.json (no image, used by hud eval) --
    remote_tasks = [
        {
            "env": {"name": env_name},
            "scenario": f"coding:{SCENARIO_NAME}",
            "args": {**args},
        }
        for args in task_registry.values()
    ]
    _write_json(remote_tasks, "remote_tasks.json")
    logger.info(f"Generated remote_tasks.json with {len(remote_tasks)} task(s)")


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

    extra_args: list[str] = args.docker_args or []
    has_failures = False

    if extra_args:
        logger.info(f"Extra args after '--': {extra_args}")

    # Resolve tasks: use --ids to filter, otherwise auto-discover all.
    needs_tasks = args.validate or args.run or args.json
    task_registry: dict[str, dict[str, Any]] = {}
    if needs_tasks:
        all_tasks = discover_tasks()
        if args.ids:
            task_registry = {k: v for k, v in all_tasks.items() if k in args.ids}
            missing = set(args.ids) - set(task_registry.keys())
            if missing:
                logger.warning(f"Requested task IDs not found: {missing}")
        else:
            task_registry = all_tasks
        if not task_registry:
            logger.error("No tasks found. Define tasks via coding_bug.task() in tasks.py.")
            return 1

    # --- Build ---
    if args.build:
        ok = await build_image(image, extra_args=extra_args or None)
        if not ok:
            return 1

    # --- Validate ---
    if args.validate:
        logger.info(f"Validating {len(task_registry)} task(s) × {len(VALIDATE_MODES)} modes ...")
        passed, failed = await validate_all(
            image,
            task_registry,
            docker_args=extra_args or None,
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
        logger.info(f"Running {len(task_registry)} task(s) (max_steps={args.max_steps}) ...")
        succeeded, failed_runs = await run_all(
            image,
            task_registry,
            args.max_steps,
            docker_args=extra_args or None,
        )

        logger.info("")
        logger.info("Run summary:")
        if succeeded:
            logger.info(f"  Succeeded ({len(succeeded)}):")
            for name, reward in succeeded:
                logger.info(f"    {name}: reward={reward}")
        if failed_runs:
            logger.error(f"  Failed ({len(failed_runs)}):")
            for name, reward in failed_runs:
                logger.error(f"    {name}: reward={reward}")
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
        generate_json(image, task_registry)

    return 1 if has_failures else 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Build, validate, run, push, and generate JSON for coding-template Docker images."),
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
        help="Task IDs to validate / run (default: all tasks)",
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
        help="Validate tasks (baseline_fail + golden_pass, 0 agent steps)",
    )
    parser.add_argument(
        "-r",
        "--run",
        action="store_true",
        help="Run agent against tasks",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Generate problem-metadata.json",
    )

    # Options -------------------------------------------------------------
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Max agent steps for --run (default: 20)",
    )

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if "--" in raw_argv:
        split_idx = raw_argv.index("--")
        our_argv = raw_argv[:split_idx]
        docker_args = raw_argv[split_idx + 1 :]
    else:
        our_argv = raw_argv
        docker_args = []

    args = parser.parse_args(our_argv)
    args.docker_args = docker_args

    if not any([args.build, args.push, args.validate, args.run, args.json]):
        logger.warning("No action flags provided (-b, -p, -v, -r, -j). Nothing to do.")
        return 0

    if args.build and (args.validate or args.run):
        if docker_args:
            parser.error(
                "-b and -v/-r are mutually exclusive when passing args after --. "
                "Run build and validate/run as separate commands."
            )

    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
