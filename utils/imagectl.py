#!/usr/bin/env python3
"""
Build Docker images for each registered problem's baseline branch and
optionally push them.

Behavior:
- Imports all tasks to populate PROBLEM_REGISTRY
- Filters problems by ids
- Computes image tag as base + spec.id (base is a required first argument)
- Actions controlled by flags:
  --build/-b: Build Docker images
  --push/-p: Push Docker images to registry
  --validate/-v: Validate images before pushing
  --json/-j: Generate problems-metadata.json file
- Flags can be combined (e.g., -bpvj)
- If no action flags are given, nothing is performed
- Parallelism: --jobs creates N threads for concurrent operations
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

# Ensure MCP tools do not load during import
os.environ["MCP_TESTING_MODE"] = "0"

# Add parent directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tasks
from grading.spec import PROBLEM_REGISTRY
from grading.utils import import_submodules
from scenarios import spec_to_statement

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Import all tasks so their @problem decorators register specs
import_submodules(tasks)


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

    parser.add_argument("--ids", nargs="+", help="Include only problems with the specified ids")
    parser.add_argument(
        "--ids-file",
        help="Path to a file containing problem ids, one per line (use '-' for stdin)",
    )
    parser.add_argument(
        "--hints",
        choices=["none", "all"],
        default="none",
        help="Hint mode to build: none (default), all. Sets HINTS for the image build.",
    )
    parser.add_argument(
        "--repo-url",
        help="Git repository URL to clone (or set REPO_URL env var)",
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
    image: str
    base: str
    test: str
    golden: str
    hints: Literal["none", "all"]


def filter_specs(args: argparse.Namespace) -> list[ProcessedSpec]:
    selected_ids = compute_selected_ids(args)

    filtered: list[ProcessedSpec] = []
    for spec in PROBLEM_REGISTRY:
        if selected_ids and spec.id not in selected_ids:
            continue

        image_base = args.base

        processed = ProcessedSpec(
            id=spec.id,
            image=image_base,
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


def build_single_image(image: str, context_dir: str, *, hints: str, repo_url: str | None = None) -> bool:
    """Build a single Docker image containing all problems.

    Patches for all problems are generated at build time and stored in /home/root/patches/.
    The PROBLEM_ID env var selects which patches to apply at runtime.
    """
    github_token = os.environ.get("CODING_GITHUB_TOKEN", "")
    if not github_token:
        logger.warning("CODING_GITHUB_TOKEN not set - private repo clone may fail")

    repo_url = repo_url or os.environ.get("REPO_URL", "")
    if not repo_url:
        logger.error("REPO_URL not set - pass --repo-url or set REPO_URL env var")
        return False

    cmd = [
        "docker",
        "build",
        "-t",
        image,
    ]

    if github_token:
        cmd.extend(["--secret", "id=github_token,env=CODING_GITHUB_TOKEN"])

    cmd.extend([
        "-f",
        os.path.join(context_dir, "Dockerfile.hud"),
        "--build-arg",
        f"REPO_URL={repo_url}",
        "--build-arg",
        f"HINTS={hints}",
        "--add-host=host.docker.internal:172.17.0.1",
        context_dir,
    ])
    logger.info(f"Building image {image} (HINTS={hints})")
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
    """Generate v4-compatible HUD task dict."""
    original_spec = next((s for s in PROBLEM_REGISTRY if s.id == spec.id), None)
    hints_enabled = spec.hints == "all"

    if original_spec:
        full_prompt = spec_to_statement(original_spec, hints_enabled=hints_enabled)
    else:
        full_prompt = f"Complete task {spec.id}."

    result = {
        "id": spec.id,
        "prompt": full_prompt,
        "setup_tool": {
            "name": "setup_problem",
            "arguments": {"problem_id": spec.id},
        },
        "evaluate_tool": {
            "name": "grade_problem",
            "arguments": {"problem_id": spec.id, "transcript": "dummy transcript"},
        },
        "agent_config": {
            "allowed_tools": ["*"],
            "disallowed_tools": ["*setup*", "*evaluate*", "*grade*"],
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


def problems_metadata_dict(spec: ProcessedSpec) -> dict:
    """Generate problem metadata dict for problems-metadata.json."""
    original_spec = next((s for s in PROBLEM_REGISTRY if s.id == spec.id), None)
    hints_enabled = spec.hints == "all"

    if original_spec:
        full_prompt = spec_to_statement(original_spec, hints_enabled=hints_enabled)
        difficulty = original_spec.difficulty
        task_type = original_spec.task_type
    else:
        full_prompt = f"Complete task {spec.id}."
        difficulty = "medium"
        task_type = "coding"

    return {
        "image": spec.image,
        "startup_command": "/mcp_server/.venv/bin/hud_eval",
        "id": spec.id,
        "required_tools": ["bash", "str_replace_editor"],
        "metadata": {
            "difficulty": difficulty,
            "description": full_prompt,
            "task_type": task_type,
        },
        "system_prompt": "",
        "enable_anthropic_api": True,
        "enabled_package_managers": [],
        "output_directory": "/tmp/out",
    }


def generate_problems_metadata_json(specs: list[ProcessedSpec]) -> None:
    """Generate problems-metadata.json file."""
    problems = [problems_metadata_dict(spec) for spec in specs]

    # [CUSTOMIZE] Update metadata for your project
    output = {
        "problem_set": {
            "owner": "[YOUR_ORG]",
            "name": "[PROBLEM_SET_NAME]",
            "description": "[PROBLEM_SET_DESCRIPTION]",
            "problems": problems,
            "version": "1.0.0",
            "created_at": "2025-01-01T00:00:00Z",
            "metadata": {
                "category": "coding",
                "language": "[LANGUAGE]",
                "difficulty": "medium",
            },
        }
    }

    output_file = "problems-metadata.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    logger.info(f"Generated {output_file} with {len(problems)} problems")


def generate_jsons(specs: list[ProcessedSpec]) -> None:
    """Generate local and remote HUD JSON files + problems-metadata.json."""
    combinations: list[tuple[bool, str]] = [
        (True, "local-hud.json"),
        (False, "remote-hud.json"),
    ]

    for local, output_file in combinations:
        results = [hud_dict(spec, local=local) for spec in specs]
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
            f.write("\n")
        logger.info(f"Generated {output_file} with {len(results)} problems")

    # Also generate problems-metadata.json
    generate_problems_metadata_json(specs)


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
        generate_jsons(specs)

    # Build single image (v5: one image contains all problems)
    image_name = args.base
    context_dir = repo_root()
    build_failed = False

    if args.build:
        hints = getattr(args, "hints", "none")
        repo_url = getattr(args, "repo_url", None)
        if not build_single_image(image_name, context_dir, hints=hints, repo_url=repo_url):
            build_failed = True

    # Push the single image
    if args.push and not build_failed:
        if not image_exists_locally(image_name):
            logger.error(f"Image not found locally for push: {image_name}")
            build_failed = True
        else:
            if not push_image(image_name):
                build_failed = True

    # Validate per-problem (runs inside the single image)
    validated_ok: list[str] = []
    validated_fail: list[str] = []
    if args.validate and not build_failed:
        for spec in specs:
            if validate_image(image_name, spec.id):
                validated_ok.append(spec.id)
            else:
                validated_fail.append(spec.id)

        logger.info("")
        logger.info("Validation summary:")
        if validated_ok:
            logger.info(f"  Validated successfully ({len(validated_ok)}): {', '.join(validated_ok)}")
        if validated_fail:
            logger.info(f"  Validation failures   ({len(validated_fail)}): {', '.join(validated_fail)}")

    # Exit non-zero if any failures
    if build_failed or validated_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
