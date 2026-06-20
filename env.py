"""Coding environment (HUD v6): a sandboxed repo the agent fixes bugs in.

The env publishes one ``ssh`` capability (a uid-walled Workspace); the agent's
harness brings its own bash/file tools. A task is a ``@env.template`` async
generator — yield a prompt, then yield a reward. Grading is 3-branch
(``{task}_baseline``/``_test``/``_golden``): ``setup_task`` checks out the
baseline and generates the hidden test patch; ``AgentPatchGrader`` applies it to
an isolated copy and runs pytest at grade time.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hud.environment import Environment, Workspace
from hud.graders import combine

from grading import AgentPatchGrader, ValidateMode

logger = logging.getLogger(__name__)

FOLDER_NAME = os.environ.get("FOLDER_NAME", "project")
REPO_URL = os.environ.get("REPO_URL", "https://github.com/hud-evals/coding-template-sample")

# The built image pins PROJECT_DIR/PATCHES_DIR to the build-time clone. Locally
# they're unset, so fall back to a per-process dir (keyed on pid so concurrent
# --runtime local rollouts don't clobber each other) under the system temp dir —
# NOT in-repo, or git apply/pytest climb to this repo's root (porting notes §15.D).
_explicit_dir = os.environ.get("PROJECT_DIR")
if _explicit_dir:
    PROJECT_DIR = _explicit_dir
    PATCHES_DIR = os.environ.get("PATCHES_DIR", "/home/root/patches")
    _LOCAL_SUBSTRATE = False
else:
    _LOCAL_ROOT = Path(tempfile.gettempdir()) / f"hud-{FOLDER_NAME}"
    PROJECT_DIR = str(_LOCAL_ROOT / f"{FOLDER_NAME}-{os.getpid()}")
    PATCHES_DIR = str(_LOCAL_ROOT / f"patches-{os.getpid()}")
    _LOCAL_SUBSTRATE = True


env = Environment(name="coding")


class UidWallWorkspace(Workspace):
    """Workspace that drops the agent shell to uid 1000.

    bwrap is unusable on the hosted runner (no user namespaces), so we run
    without it and protect the answer key with a uid wall: ``setpriv`` drops the
    shell to the repo-owner uid, so the agent can edit the repo but can't read
    the root:700 ``.git`` / patches. No-op off root (local). See notes §15.H.
    """

    def shell_argv(self, command=None, *, cwd=None, env=None):
        argv = super().shell_argv(command, cwd=cwd, env=env)
        if sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() == 0:
            argv = ["setpriv", "--reuid", "1000", "--regid", "1000", "--clear-groups", "--", *argv]
        return argv


_ws = UidWallWorkspace(
    PROJECT_DIR,
    guest_path=PROJECT_DIR,
    network=True,
    env={"HOME": "/home/ubuntu"},
)


async def _ensure_repo() -> None:
    if (Path(PROJECT_DIR) / ".git").exists():
        return
    Path(PROJECT_DIR).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s into %s", REPO_URL, PROJECT_DIR)
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", REPO_URL, PROJECT_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git clone {REPO_URL} failed: {stderr.decode(errors='replace')}")


@env.initialize
async def _up() -> None:
    # Clone before starting the workspace: clone needs PROJECT_DIR absent; the
    # workspace then writes its ssh credentials into PROJECT_DIR/.hud.
    await _ensure_repo()
    await _ws.start()
    env.add_capability(_ws.capability("shell"))


@env.shutdown
async def _down() -> None:
    await _ws.stop()
    if _LOCAL_SUBSTRATE:
        shutil.rmtree(PROJECT_DIR, ignore_errors=True)
        shutil.rmtree(PATCHES_DIR, ignore_errors=True)


def setup_task(task_id: str, validate_mode: ValidateMode | None = None) -> None:
    """Generate the hidden test.patch and check out the baseline (or golden, to validate)."""
    base = f"{task_id}_baseline"
    test = f"{task_id}_test"
    golden = f"{task_id}_golden"

    os.environ["PROBLEM_ID"] = task_id
    task_patches_dir = os.path.join(PATCHES_DIR, task_id)
    os.makedirs(task_patches_dir, exist_ok=True)

    diff = subprocess.run(
        ["git", "diff", f"origin/{base}", f"origin/{test}"],
        cwd=PROJECT_DIR, capture_output=True, text=True,
    )
    with open(os.path.join(task_patches_dir, "test.patch"), "w") as f:
        f.write(diff.stdout)

    checkout_branch = golden if validate_mode == "golden_pass" else base
    result = subprocess.run(
        ["git", "checkout", "-f", f"origin/{checkout_branch}"],
        cwd=PROJECT_DIR, capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error("Failed to checkout %s: %s", checkout_branch, result.stderr)
    elif hasattr(os, "geteuid") and os.geteuid() == 0:
        # Re-assert the uid wall after checkout (image only): repo -> agent, .git -> root.
        subprocess.run(["chown", "-R", "ubuntu:ubuntu", PROJECT_DIR], capture_output=True)
        subprocess.run(["chown", "-R", "root:root", os.path.join(PROJECT_DIR, ".git")], capture_output=True)

    os.chdir(PROJECT_DIR)


def make_prompt(description: str) -> str:
    return f"""You are working in a coding repository located at {PROJECT_DIR}.

Use the tools provided to complete the following task:

{description}
"""


@env.template(id="coding-bug", description="Fix a bug in the target repository.")
async def coding_bug(
    task_id: str,
    description: str,
    test_files: list[str],
    validate_mode: ValidateMode | None = None,
):
    setup_task(task_id=task_id, validate_mode=validate_mode)
    _ = yield make_prompt(description)
    yield await combine(
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id=task_id,
            test_files=test_files,
            validate_mode=validate_mode,
            repo_path=PROJECT_DIR,
            patches_dir=PATCHES_DIR,
        )
    )
