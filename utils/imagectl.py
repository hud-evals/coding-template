#!/usr/bin/env python3
"""
Build Rocket.Chat Docker images for each registered problem's baseline branch and
optionally push them. Mirrors filtering logic from utils/generate_problems_json.py.

Behavior:
- Imports all extractors to populate PROBLEM_REGISTRY
- Filters problems by review level, ids, include-too-hard, include-demo
- Computes image tag as base + spec.id (base is a required first argument)
- Actions controlled by flags:
  --build/-b: Build Docker images
  --push/-p: Push Docker images to registry
  --validate/-v: Validate images before pushing
  --json/-j: Generate local-hud.json file and remote-hud.json file
- Flags can be combined (e.g., -bpvj)
- If no action flags are given, nothing is performed
- Parallelism: --jobs creates N threads for concurrent operations
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, get_args

# Ensure MCP tools do not load during import
os.environ["MCP_TESTING_MODE"] = "0"

import server.problems
from server.main import spec_to_statement
from server.spec import PROBLEM_REGISTRY, ReviewLevel
from server.utils import import_submodules

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Import all problems so their @problem decorators register specs
import_submodules(server.problems)


def repo_root() -> str:
    """Return absolute path to the repository root (where Dockerfile lives)."""
    # This file is located at <repo_root>/utils/generate_docker_images.py
    utils_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(utils_dir, ".."))


def add_common_filters(parser: argparse.ArgumentParser) -> None:
    # Add base as the first mandatory positional argument
    parser.add_argument(
        "base",
        help="Required image base name (the problem id will be appended)",
    )

    review_levels = get_args(ReviewLevel)
    for level in review_levels:
        parser.add_argument(
            f"--{level.replace('-', '_')}",
            action="store_true",
            help=f"Include problems with review level: {level}",
        )

    parser.add_argument("--ids", nargs="+", help="Include only problems with the specified ids")
    parser.add_argument(
        "--ids-file",
        help="Path to a file containing problem ids, one per line (use '-' for stdin)",
    )
    parser.add_argument(
        "--include-too-hard",
        action="store_true",
        help="Include problems marked as too hard",
        default=False,
    )
    parser.add_argument(
        "--include-demo",
        action="store_true",
        help="Include demo problems",
        default=False,
    )
    parser.add_argument(
        "--hints",
        choices=["none", "all"],
        default="none",
        help="Hint mode to build: none (default), all. Sets HINTS for the image build.",
    )


def compute_selected_ids(args: argparse.Namespace) -> set[str]:
    selected_ids: set[str] = set()
    if getattr(args, "ids", None):
        selected_ids.update(args.ids)
    if getattr(args, "ids_file", None):
        if args.ids_file == "-":
            id_lines = sys.stdin.read().splitlines()
        else:
            with open(args.ids_file, encoding="utf-8") as f:
                id_lines = f.read().splitlines()
        selected_ids.update(line.strip() for line in id_lines if line.strip())
    return selected_ids


@dataclass
class ProcessedSpec:
    id: str
    description: str
    image: str
    base: str
    test: str
    golden: str
    hints: Literal["none", "all"]


def filter_specs(args: argparse.Namespace) -> list[ProcessedSpec]:
    review_levels = get_args(ReviewLevel)
    selected_review_levels: list[str] = []
    for level in review_levels:
        if getattr(args, level.replace("-", "_")):
            selected_review_levels.append(level)

    selected_ids = compute_selected_ids(args)

    filtered: list[ProcessedSpec] = []
    for spec in PROBLEM_REGISTRY:
        if selected_review_levels and spec.review_level not in selected_review_levels:
            continue
        if selected_ids and spec.id not in selected_ids:
            continue
        if spec.too_hard and not args.include_too_hard:
            continue
        if spec.demo and not args.include_demo:
            continue

        image_base = args.base

        processed = ProcessedSpec(
            id=spec.id,
            description=spec.description,
            image=image_base + spec.id,
            base=spec.base,
            test=spec.test,
            golden=spec.golden,
            hints=getattr(args, "hints", "none"),
        )

        filtered.append(processed)
    return filtered


def run_command(cmd: list[str], prefix: str) -> int:
    """Run a command streaming output; return exit code."""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(f"{prefix} {line}")
    process.wait()
    return int(process.returncode or 0)


def build_image(
    image: str,
    baseline_branch: str,
    test_branch: str,
    golden_branch: str,
    context_dir: str,
    *,
    hints: str,
    problem_id: str,
) -> bool:
    cmd = [
        "docker",
        "build",
        "-t",
        image,
        "--build-arg",
        f"PROBLEM_ID={problem_id}",
        "--build-arg",
        f"BASELINE_BRANCH={baseline_branch}",
        "--build-arg",
        f"TEST_BRANCH={test_branch}",
        "--build-arg",
        f"GOLDEN_BRANCH={golden_branch}",
        "--build-arg",
        f"HINTS={hints}",
        "--add-host=host.docker.internal:172.17.0.1",
        context_dir,
    ]
    logger.info(
        f"Building image {image} (BASELINE_BRANCH={baseline_branch}, TEST_BRANCH={test_branch}, GOLDEN_BRANCH={golden_branch}, HINTS={hints}, PROBLEM_ID={problem_id})"
    )
    rc = run_command(cmd, prefix=f"[build {image}] ")
    if rc != 0:
        logger.error(f"Build failed for {image} (exit code {rc})")
        return False
    logger.info(f"Build succeeded for {image}")
    return True


def image_exists_locally(image: str) -> bool:
    rc = subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return rc.returncode == 0


def validate_image(image: str, problem_id: str) -> bool:
    """Run validation inside the Docker container using validate_problem script."""
    logger.info(f"Validating image {image} for problem {problem_id}")
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        image,
        "validate_problem",
        problem_id,
    ]
    rc = run_command(cmd, prefix=f"[validate {image}] ")
    if rc != 0:
        logger.error(f"Validation failed for {image} (exit code {rc})")
        return False
    logger.info(f"Validation succeeded for {image}")
    return True


def push_image(image: str) -> bool:
    logger.info(f"Pushing image {image}")
    rc = run_command(["docker", "push", image], prefix=f"[push  {image}] ")
    if rc != 0:
        logger.error(f"Push failed for {image} (exit code {rc})")
        return False
    logger.info(f"Push succeeded for {image}")
    return True


def hud_dict(spec: ProcessedSpec, local: bool) -> dict:
    result = {
        "id": spec.id,
        "prompt": spec_to_statement(spec),
        "setup_tool": {
            "name": "setup_problem",
            "arguments": {"problem_id": spec.id},
        },
        "evaluate_tool": {
            "name": "grade_problem",
            "arguments": {"problem_id": spec.id, "transcript": "dummy transcript"},
        },
        "agent_config": {
            "allowed_tools": ["bash", "str_replace_editor", "computer"],
        },
    }

    if local:
        result["mcp_config"] = {
            "local": {
                "command": "docker",
                "args": [
                    "run",
                    "--rm",
                    "-i",
                    spec.image,
                ],
            }
        }
    else:
        result["mcp_config"] = {
            "hud": {
                "url": "https://mcp.hud.so/v3/mcp",
                "headers": {
                    "Authorization": "Bearer ${HUD_API_KEY}",
                    "Mcp-Image": spec.image,
                },
            }
        }

    return result

def generate_local_hud_json(specs: list[ProcessedSpec], output_file: str = "local-hud.json") -> None:
    results = [hud_dict(spec, local=True) for spec in specs]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    logger.info(f"Generated {output_file} with {len(results)} problems")

def generate_remote_hud_json(specs: list[ProcessedSpec], output_file: str = "remote-hud.json") -> None:
    results = [hud_dict(spec, local=False) for spec in specs]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    logger.info(f"Generated {output_file} with {len(results)} problems")


def run_pipeline(
    specs: list[ProcessedSpec],
    *,
    build: bool,
    push: bool,
    validate: bool,
    jobs: int = 1,
) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    """
    Execute the build/push pipeline with specified number of concurrent workers.

    Args:
        specs: List of problem specs to build/push
        build: Whether to build Docker images
        push: Whether to push images to registry
        validate: Whether to validate images
        jobs: Number of parallel workers for operations

    Returns:
        (built_success, built_failed, validated_success, validated_failed, pushed_success, pushed_failed)
    """
    context_dir = repo_root()

    build_queue: queue.Queue[ProcessedSpec | None] = queue.Queue()
    validate_queue: queue.Queue[tuple[ProcessedSpec, str] | None] = queue.Queue()
    push_queue: queue.Queue[str | None] = queue.Queue()

    built_success: list[str] = []
    built_failed: list[str] = []
    validated_success: list[str] = []
    validated_failed: list[str] = []
    pushed_success: list[str] = []
    pushed_failed: list[str] = []
    lists_lock = threading.Lock()

    total_builds = len(specs) if build else 0
    total_validates = len(specs) if validate else 0
    total_pushes = len(specs) if push else 0
    build_index_counter = [0]
    validate_index_counter = [0]
    push_index_counter = [0]

    def build_worker() -> None:
        while True:
            item = build_queue.get()
            if item is None:
                build_queue.task_done()
                break
            spec = item
            image = spec.image
            ok = build_image(
                image=image,
                baseline_branch=spec.base,
                test_branch=spec.test,
                golden_branch=spec.golden,
                context_dir=context_dir,
                hints=spec.hints,
                problem_id=spec.id,
            )
            with lists_lock:
                build_index_counter[0] += 1
                current_index = build_index_counter[0]
                (built_success if ok else built_failed).append(image)
            percent = int((current_index / total_builds) * 100) if total_builds > 0 else 0
            logger.info(f"=========== BUILD {current_index}/{total_builds} ({percent}% completed) ===========")
            if ok:
                if validate:
                    # Queue for validation
                    validate_queue.put((spec, image))
                elif push:
                    # If no validation, queue directly for push
                    push_queue.put(image)
            build_queue.task_done()

    def push_worker() -> None:
        while True:
            image = push_queue.get()
            if image is None:
                push_queue.task_done()
                break
            # Verify image exists locally before pushing
            if not image_exists_locally(image):
                logger.error(f"Image not found locally for push: {image}")
                with lists_lock:
                    push_index_counter[0] += 1
                    current_index = push_index_counter[0]
                    pushed_failed.append(image)
                percent = int((current_index / total_pushes) * 100) if total_pushes > 0 else 0
                logger.info(f"=========== PUSH {current_index}/{total_pushes} ({percent}% completed) ===========")
                push_queue.task_done()
                continue
            ok = push_image(image)
            with lists_lock:
                push_index_counter[0] += 1
                current_index = push_index_counter[0]
                (pushed_success if ok else pushed_failed).append(image)
            percent = int((current_index / total_pushes) * 100) if total_pushes > 0 else 0
            logger.info(f"=========== PUSH {current_index}/{total_pushes} ({percent}% completed) ===========")
            push_queue.task_done()

    def validate_worker() -> None:
        while True:
            item = validate_queue.get()
            if item is None:
                validate_queue.task_done()
                break
            spec, image = item
            ok = validate_image(image, spec.id)
            with lists_lock:
                validate_index_counter[0] += 1
                current_index = validate_index_counter[0]
                (validated_success if ok else validated_failed).append(image)
            percent = int((current_index / total_validates) * 100) if total_validates > 0 else 0
            logger.info(f"=========== VALIDATE {current_index}/{total_validates} ({percent}% completed) ===========")
            if ok and push:
                # Only push if validation succeeded
                push_queue.put(image)
            validate_queue.task_done()

    # Create worker threads based on jobs parameter
    threads: list[threading.Thread] = []

    # If not building, handle validate and/or push for existing images
    if not build:
        if validate:
            for i in range(jobs):
                t_validate = threading.Thread(target=validate_worker, daemon=True, name=f"validate-worker-{i + 1}")
                t_validate.start()
                threads.append(t_validate)

            if push:
                for i in range(jobs):
                    t_push = threading.Thread(target=push_worker, daemon=True, name=f"push-worker-{i + 1}")
                    t_push.start()
                    threads.append(t_push)

            for spec in specs:
                # Check if image exists locally before queuing for validation
                if image_exists_locally(spec.image):
                    validate_queue.put((spec, spec.image))
                else:
                    logger.error(f"Image not found locally for validation: {spec.image}")
                    with lists_lock:
                        validated_failed.append(spec.image)

            # Send termination signals
            for _ in range(jobs):
                validate_queue.put(None)
            validate_queue.join()

            if push:
                for _ in range(jobs):
                    push_queue.put(None)
                push_queue.join()
        elif push:
            # No validation, direct push
            for i in range(jobs):
                t_push = threading.Thread(target=push_worker, daemon=True, name=f"push-worker-{i + 1}")
                t_push.start()
                threads.append(t_push)

            for spec in specs:
                if image_exists_locally(spec.image):
                    push_queue.put(spec.image)
                else:
                    logger.error(f"Image not found locally for push: {spec.image}")
                    with lists_lock:
                        pushed_failed.append(spec.image)

            # Send termination signals for all push workers
            for _ in range(jobs):
                push_queue.put(None)
            push_queue.join()

        for t in threads:
            t.join()
        return built_success, built_failed, validated_success, validated_failed, pushed_success, pushed_failed

    # Start validation workers if validating
    if validate:
        for i in range(jobs):
            t_validate = threading.Thread(target=validate_worker, daemon=True, name=f"validate-worker-{i + 1}")
            t_validate.start()
            threads.append(t_validate)

    # Start push workers if pushing
    if push:
        for i in range(jobs):
            t_push = threading.Thread(target=push_worker, daemon=True, name=f"push-worker-{i + 1}")
            t_push.start()
            threads.append(t_push)

    # Start build workers
    for i in range(jobs):
        t_build = threading.Thread(target=build_worker, daemon=True, name=f"build-worker-{i + 1}")
        t_build.start()
        threads.append(t_build)

    # Enqueue all builds
    for spec in specs:
        build_queue.put(spec)

    # Send termination signals for all build workers
    for _ in range(jobs):
        build_queue.put(None)

    # Wait for builds
    build_queue.join()

    # If validating, send termination signals and wait for validation queue
    if validate:
        for _ in range(jobs):
            validate_queue.put(None)
        validate_queue.join()

    # If pushing concurrently, send termination signals and wait for push queue
    if push:
        for _ in range(jobs):
            push_queue.put(None)
        push_queue.join()

    for t in threads:
        t.join()

    return built_success, built_failed, validated_success, validated_failed, pushed_success, pushed_failed


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build, validate, and/or push Docker images for HUD problems.")
    add_common_filters(parser)

    # Add action flags with short forms
    parser.add_argument(
        "-b",
        "--build",
        action="store_true",
        help="Build Docker images",
    )
    parser.add_argument(
        "-p",
        "--push",
        action="store_true",
        help="Push images to registry",
    )
    parser.add_argument(
        "-v",
        "--validate",
        action="store_true",
        help="Validate images by running 'validate_problem <problem_id>' inside the container",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Generate problems-metadata.json file",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="Number of parallel jobs for operations (default: 1)", metavar="N"
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    specs = filter_specs(args)
    if not specs:
        logger.warning("No problems matched the provided filters.")
        return 0

    # Check if any action flag is provided
    if not (args.build or args.push or args.validate or args.json):
        logger.warning("No action flags provided (--build, --push, --validate, or --json). Nothing to do.")
        return 0

    # Generate JSON if requested (runs first)
    if args.json:
        generate_local_hud_json(specs, "local-hud.json")
        generate_remote_hud_json(specs, "remote-hud.json")

    # Only run pipeline if build, push, or validate is requested
    if args.build or args.push or args.validate:
        # Validate that if push or validate is requested without build, images exist
        if (args.push or args.validate) and not args.build:
            missing_images = [spec.image for spec in specs if not image_exists_locally(spec.image)]
            if missing_images:
                logger.warning("Warning: The following images do not exist locally and --build was not specified:")
                for img in missing_images:
                    logger.warning(f"  - {img}")
                logger.warning("These images will fail to push/validate.")

        built_ok, built_fail, validated_ok, validated_fail, pushed_ok, pushed_fail = run_pipeline(
            specs,
            build=args.build,
            push=args.push,
            validate=args.validate,
            jobs=args.jobs,
        )
    else:
        # Only JSON was requested, no pipeline run
        built_ok = built_fail = validated_ok = validated_fail = pushed_ok = pushed_fail = []

    # Only print summaries if pipeline was run
    if args.build or args.push or args.validate:
        logger.info("")
        if args.build and (built_ok or built_fail):
            logger.info("Build summary:")
            if built_ok:
                logger.info(f"  Built successfully ({len(built_ok)}): {', '.join(built_ok)}")
            if built_fail:
                logger.info(f"  Build failures   ({len(built_fail)}): {', '.join(built_fail)}")
        if args.validate and (validated_ok or validated_fail):
            logger.info("Validation summary:")
            if validated_ok:
                logger.info(f"  Validated successfully ({len(validated_ok)}): {', '.join(validated_ok)}")
            if validated_fail:
                logger.info(f"  Validation failures   ({len(validated_fail)}): {', '.join(validated_fail)}")
        if args.push and (pushed_ok or pushed_fail):
            logger.info("Push summary:")
            if pushed_ok:
                logger.info(f"  Pushed successfully ({len(pushed_ok)}): {', '.join(pushed_ok)}")
            if pushed_fail:
                logger.info(f"  Push failures      ({len(pushed_fail)}): {', '.join(pushed_fail)}")

    # Exit non-zero if any failures
    if built_fail or validated_fail or pushed_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
