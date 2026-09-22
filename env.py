"""Coding environment (HUD v6): a repo workspace with diff-based grading.

The env publishes one ``ssh`` workspace over a git repo; the agent's harness
brings its own bash/file tools. Task setup vaults the repo's real history
(:mod:`coding.repo`) so the agent gets a fresh single-commit repo with working
git but no answer-key refs; grading captures the agent's changes as a diff,
resets to the pre-agent snapshot, re-applies, and runs the graders.

Four task templates:

- ``swe-task`` — one image serves every task. Everything task-specific
  arrives as uploads: the codebase zip, the grading zip (``run_grading.sh``,
  ``criteria.json``, hidden tests, optional ``setup.sh`` / ``services.sh``),
  an optional ``gold.diff`` and an optional ``llm_rubric.json``. New tasks
  are new uploads; nothing is rebuilt or redeployed.
- ``coding-task`` — hidden tests live as refs in the repo's vaulted history
  (the ``{task}_baseline`` / ``{task}_test`` / ``{task}_golden`` branch
  convention) and a shell command scores by exit code.
- ``sdlc-task`` — adds workflow: a bare mock-GitHub remote the agent pushes
  to, ``github_*`` issue/PR tools (:mod:`coding.github`), and grading over
  the pushed pull-request branch instead of the worktree.
- one SWE-bench Pro instance template, registered only when an instance dir
  is baked in (see ``swe_tasks.py``): grading replays the official evaluator
  (:mod:`coding.swe_bench_pro`).

Images set ``REPO_DIR``; locally everything lives in per-process temp dirs.
Everything answer-key-shaped sits under ``/hud`` (root, mode 700) and agent
shells drop to a non-root uid, so only the env process can read it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import warnings
from pathlib import Path
from typing import Annotated, Any

from hud.environment import Environment, Workspace
from hud.graders import BashGrader, EvaluationResult, LLMJudgeGrader, SubScore, combine
from hud.settings import settings
from pydantic import Field, TypeAdapter

from coding import judge as judge_lib
from coding import repo as repo_lib
from coding import swe_bench_pro as swe
from coding.github import MockGitHub
from coding.github import serve as serve_github
from coding.uploads import (
    CriterionRow,
    DataFileError,
    DataFileRef,
    RubricRow,
    criterion_id,
    load_criteria,
    load_rubric,
    stage,
)

logger = logging.getLogger(__name__)

# ─── substrate layout ────────────────────────────────────────────────────
# Images set REPO_DIR (an empty /workspace/repo the task fills); locally
# everything lives in per-process temp dirs.

_explicit_repo = os.environ.get("REPO_DIR")
if _explicit_repo:
    REPO_DIR = Path(_explicit_repo)
    VAULT_DIR = Path(os.environ.get("VAULT_DIR", "/hud/vault"))
    LOGS_DIR = Path(os.environ.get("GRADING_LOGS_DIR", "/hud/logs"))
    GRADER_DIR = Path(os.environ.get("GRADER_DIR", "/hud/grader"))
    _LOCAL_SUBSTRATE = False
else:
    _LOCAL_ROOT = Path(tempfile.gettempdir()) / "hud-coding"
    REPO_DIR = _LOCAL_ROOT / f"repo-{os.getpid()}"
    VAULT_DIR = _LOCAL_ROOT / f"vault-{os.getpid()}"
    LOGS_DIR = _LOCAL_ROOT / f"logs-{os.getpid()}"
    GRADER_DIR = _LOCAL_ROOT / f"grader-{os.getpid()}"
    _LOCAL_SUBSTRATE = True

# The SDLC flavor's mock-GitHub remote: a bare repo the agent pushes to. It
# must be writable by the agent, so it lives outside /hud.
REMOTE_DIR = (
    Path(os.environ.get("REMOTE_DIR", "/srv/git/project.git"))
    if _explicit_repo
    else _LOCAL_ROOT / f"remote-{os.getpid()}" / "project.git"
)

# The git-ref flavors' substrate. Only cloned when set: swe-task fills the
# workspace from its own uploaded zip, so the default is an empty repo dir.
REPO_URL = os.environ.get("REPO_URL")
TESTS_TIMEOUT = float(os.environ.get("GRADING_TIMEOUT", "3600"))
SETUP_TIMEOUT = float(os.environ.get("SETUP_TIMEOUT", "1800"))

INSTANCE_DIR = Path(os.environ.get("INSTANCE_DIR", "/hud/instance"))

AGENT_UID = 1000
AGENT_HOME = Path("/tmp/agent-home")  # noqa: S108 - container-local, created at setup

env = Environment(name="swe-task-example")


# shell_uid is the privilege wall: the env process (root, in images) keeps the
# vault and instance assets under /hud at mode 700; the uid-dropped agent can
# edit the repo but never read the answer key. No-op off root (local).
# (Requires hud>=0.6.12.dev0: earlier shell_uid recursively chowned the whole
# workspace on the serving path, missing the deploy readiness probe.)
_AGENT_ENV = {"HOME": str(AGENT_HOME)}
# The image's toolchain settings (Dockerfile.hud ENV): the same caches setup
# filled, handed to the agent by _lock_down. The repo's own .venv goes first
# on PATH so `python` / `pytest` are the project's when setup made one.
_TOOLCHAIN_VARS = (
    "GOPATH GOMODCACHE GOCACHE GOTOOLCHAIN CGO_ENABLED "
    "FNM_DIR COREPACK_HOME COREPACK_ENABLE_DOWNLOAD_PROMPT COREPACK_DEFAULT_TO_LATEST npm_config_store_dir "
    "UV_PYTHON_INSTALL_DIR UV_CACHE_DIR UV_PYTHON_BIN_DIR RUSTUP_HOME CARGO_HOME"
).split()
if not _LOCAL_SUBSTRATE:
    _AGENT_ENV.update({name: os.environ[name] for name in _TOOLCHAIN_VARS if name in os.environ})
    _AGENT_ENV["PATH"] = f"{REPO_DIR / '.venv' / 'bin'}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"
_ws = Workspace(
    REPO_DIR,
    guest_path=str(REPO_DIR),
    network=True,
    env=_AGENT_ENV,
    track_files=settings.file_tracking_enabled,
    shell_uid=AGENT_UID,
)

SDLC_TOOLS = os.environ.get("SDLC_TOOLS", "") not in ("", "0", "false")

WORKSPACE_NOTE = f"Please make your changes directly in {REPO_DIR}, not in a copy or a separate worktree."

_github = MockGitHub()
_github_server: asyncio.Task[None] | None = None
# Process groups started by a task's services.sh; killed at grade and shutdown.
_service_pgids: list[int] = []


def _stop_services() -> None:
    for pgid in _service_pgids:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    _service_pgids.clear()


@env.initialize
async def _up() -> None:
    global _github_server
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if _LOCAL_SUBSTRATE and REPO_URL and not (REPO_DIR / ".git").exists():
        logger.info("cloning %s into %s", REPO_URL, REPO_DIR)
        await repo_lib.run("git", "clone", "-q", REPO_URL, str(REPO_DIR), cwd=REPO_DIR.parent)
    await _ws.start()
    env.add_capability(_ws.capability("shell"))
    if _ws.tracks_files:
        env.add_capability(_ws.file_tracking_capability())
    # The mock-GitHub tools belong to the SDLC flavor, which seeds issues and
    # wants a pull request. A plain coding task never uses them, and offering
    # them anyway spends agent steps on an empty issue list - every rollout so
    # far called github_list_issues and github_list_pull_requests once.
    if SDLC_TOOLS:
        _github_server, github_capability = serve_github(_github)
        env.add_capability(github_capability)


@env.shutdown
async def _down() -> None:
    _stop_services()
    if _github_server is not None:
        _github_server.cancel()
    await _ws.stop()
    if _LOCAL_SUBSTRATE:
        for path in (REPO_DIR, VAULT_DIR, LOGS_DIR, GRADER_DIR, REMOTE_DIR.parent):
            shutil.rmtree(path, ignore_errors=True)


# ─── shared task lifecycle ───────────────────────────────────────────────


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


async def _setup(base_ref: str | None = None, *, remote: bool = False) -> None:
    """Check out the task's baseline, vault the history, hand the repo to the agent.

    With ``remote=True`` (the SDLC flavor) a bare "GitHub" remote is created
    from the baseline first, and the agent's repo is attached to it as a
    normal clone would be — realistic history, pushes, and branches, but no
    reachable answer-key refs.
    """
    if base_ref:
        await repo_lib.git(REPO_DIR, "checkout", "-qf", base_ref)
    if remote:
        await repo_lib.create_remote(REPO_DIR, REMOTE_DIR, base_ref or "HEAD")
    await repo_lib.vault_history(REPO_DIR, VAULT_DIR)
    if remote:
        await repo_lib.attach_to_remote(REPO_DIR, REMOTE_DIR)
    if _is_root():
        AGENT_HOME.mkdir(parents=True, exist_ok=True)
        uid = f"{AGENT_UID}:{AGENT_UID}"
        paths = [str(REPO_DIR), str(AGENT_HOME)] + ([str(REMOTE_DIR)] if remote else [])
        await repo_lib.run("chown", "-R", uid, *paths, cwd=Path("/"), timeout=1200.0)
        if remote:
            # The grader (root) pushes to and clones from the agent-owned remote.
            await repo_lib.run("git", "config", "--global", "--add", "safe.directory", str(REMOTE_DIR), cwd=Path("/"))


# Text box in the console instead of a quoted JSON string. The git-ref
# flavors keep the name ``description`` so existing Toptal rows keep working.
Prompt = Annotated[str, Field(json_schema_extra={"x-hud-hint": "prompt"})]
# One uploaded file each, in the console's data-file picker shape (a list, as
# mc-bench's attachments; exactly one item here). The hint sits on the
# property itself, not inside anyOf, so an optional upload gets the picker too.
_PICKER = {"x-hud-hint": "data-files"}
Upload = Annotated[list[DataFileRef], Field(min_length=1, max_length=1, json_schema_extra=_PICKER)]
OptionalUpload = Annotated[list[DataFileRef] | None, Field(json_schema_extra=_PICKER)]
# A row may also carry the bare file id or the object; the models are applied here.
_UPLOAD = TypeAdapter(str | DataFileRef | list[DataFileRef])

# ─── swe-task: everything task-specific arrives as uploads ───────────────

GRADER_SCRIPT = "run_grading.sh"
GOLD_FILE = "gold.diff"
RUBRIC_FILE = "llm_rubric.json"
# /hud/gold.diff and /hud/llm_rubric.json in images: next to the grading
# pack, never in it, so the pack stays what a contributor zips up.
HUD_ROOT = GRADER_DIR.parent
GOLD_PATH = HUD_ROOT / GOLD_FILE
RUBRIC_PATH = HUD_ROOT / RUBRIC_FILE
# The uniform reward rule the swe-graders-v2 tasks converged on: monotone, no
# floor, a failed gate leaves at most a fifth.
BLOCKER_SCALE = 1.0 / 3.0
GATE_SCALE = 0.2
_SCORE_LINE = re.compile(r"^GRADER_SCORE\s+([0-9.]+)\s*$", re.M)


class TaskSetupError(RuntimeError):
    """A task could not be brought up; carries the fail-closed status."""

    def __init__(self, status: str, **info: Any) -> None:
        super().__init__(status)
        self.status = status
        self.info = info


def _zero(status: str, **info: Any) -> EvaluationResult:
    """A fail-closed result: a misconfigured or broken task scores 0, visibly."""
    return EvaluationResult(
        reward=0.0,
        done=True,
        content=f"status={status}",
        info={"status": status, **info},
        isError=status == "grader_error",
    )


def _failed_prompt(status: str) -> str:
    """Agent-facing text when setup dies before a real ticket can be sent."""
    return f"Task setup failed ({status}). Finish immediately."


def _upload(value: Any) -> DataFileRef | None:
    if value is None:
        return None
    parsed = _UPLOAD.validate_python(value)
    if isinstance(parsed, str):
        return DataFileRef(file_id=parsed)
    if isinstance(parsed, list):
        if len(parsed) != 1:
            raise ValueError(f"expected exactly one uploaded file, got {len(parsed)}")
        return parsed[0]
    return parsed


def _task_env() -> dict[str, str]:
    """What setup.sh, services.sh and run_grading.sh see on top of the image env."""
    return {
        **os.environ,
        "REPO_DIR": str(REPO_DIR),
        "GRADER_DIR": str(GRADER_DIR),
        "GRADER_STATE_DIR": str(LOGS_DIR / "grading-state"),
        "GRADING_LOGS_DIR": str(LOGS_DIR),
        "AGENT_HOME": str(AGENT_HOME),
        "HOME": os.environ.get("HOME") or "/root",
    }


async def _sh(
    command: str, *, cwd: Path, timeout: float, log: Path | None = None, new_session: bool = False
) -> tuple[int, str]:
    """Run one bash command with the task env; returns (rc, combined output). 124 on timeout."""
    proc = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        command,
        cwd=str(cwd),
        env=_task_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=new_session,
    )
    if new_session:
        _service_pgids.append(proc.pid)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode if proc.returncode is not None else 1
        text = out.decode("utf-8", "replace")
    except TimeoutError:
        proc.kill()
        await proc.wait()
        rc, text = 124, f"timed out after {timeout:.0f}s"
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n$ {command}\n{text}\n# exit {rc}\n")
    return rc, text


async def _stage_uploads(
    codebase: DataFileRef, grading: DataFileRef, gold: DataFileRef | None, rubric: DataFileRef | None, key: str | None
) -> None:
    """Codebase into the (empty) workspace; everything else under /hud."""
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if any(REPO_DIR.iterdir()):
        raise TaskSetupError("workspace_not_empty", path=str(REPO_DIR))
    shutil.rmtree(GRADER_DIR, ignore_errors=True)
    GRADER_DIR.mkdir(parents=True, mode=0o700)
    for stale in (GOLD_PATH, RUBRIC_PATH):
        stale.unlink(missing_ok=True)
    try:
        await stage(grading, GRADER_DIR, api_key=key)
        if not (GRADER_DIR / GRADER_SCRIPT).is_file():
            raise TaskSetupError("invalid_grading_pack", reason=f"{GRADER_SCRIPT} missing")
        await stage(codebase, REPO_DIR, api_key=key)
        if not any(REPO_DIR.iterdir()):
            raise TaskSetupError("empty_codebase")
        if gold is not None:
            await stage(gold.model_copy(update={"path": GOLD_FILE}), HUD_ROOT, api_key=key, unpack=False)
        if rubric is not None:
            await stage(rubric.model_copy(update={"path": RUBRIC_FILE}), HUD_ROOT, api_key=key, unpack=False)
    except DataFileError as exc:
        raise TaskSetupError("upload_stage_failed", reason=str(exc)[:800]) from exc


def _declares_node_version(repo: Path) -> bool:
    if (repo / ".nvmrc").is_file() or (repo / ".node-version").is_file():
        return True
    try:
        return bool(json.loads((repo / "package.json").read_text("utf-8")).get("engines", {}).get("node"))
    except (OSError, ValueError, AttributeError):
        return False


def setup_commands(repo: Path) -> list[str]:
    """Auto-setup for packs without a setup.sh: the repo's manifests say what it needs.

    The image holds installers, not versions (Dockerfile.hud), so each
    ecosystem's own resolver picks the runtime from what the repo declares:
    ``go`` switches toolchains itself from go.mod / go.work (GOTOOLCHAIN=auto),
    ``use-node`` reads .nvmrc / .node-version / engines.node through fnm (with
    no declaration the image default stays) and corepack takes pnpm / yarn
    from package.json's ``packageManager``, ``uv`` reads .python-version /
    requires-python and downloads a missing CPython. A lockfile picks the
    package manager; a bare package.json gets ``npm install``. Ecosystems
    coexist (a Go repo with a web UI), so every match contributes, and each
    block ends by printing the version it chose, for setup.log.
    """
    commands: list[str] = []
    if (repo / "go.work").is_file() or (repo / "go.mod").is_file():
        commands += ["go mod download", "go version"]
    if (repo / "package.json").is_file():
        if _declares_node_version(repo):
            commands.append("use-node")
        if (repo / "pnpm-lock.yaml").is_file():
            commands.append("pnpm install --frozen-lockfile")
        elif (repo / "yarn.lock").is_file():
            commands.append("yarn install --frozen-lockfile")
        elif (repo / "package-lock.json").is_file():
            commands.append("npm ci --no-audit --no-fund")
        else:
            commands.append("npm install --no-audit --no-fund")
        commands.append("node --version")
    if (repo / "uv.lock").is_file():
        commands += ["uv sync --frozen", ".venv/bin/python --version"]
    elif (repo / "pyproject.toml").is_file():
        # uv sync needs a [project] table; older layouts still build with pip.
        commands += ["uv sync || (uv venv && uv pip install -e .)", ".venv/bin/python --version"]
    elif (repo / "requirements.txt").is_file():
        commands += ["uv venv && uv pip install -r requirements.txt", ".venv/bin/python --version"]
    if (repo / "Cargo.toml").is_file():
        # The proxies install a rust-toolchain(.toml) pin on first use; without one, stable.
        commands += [
            "[ -e rust-toolchain ] || [ -e rust-toolchain.toml ] || rustup default stable",
            "cargo fetch",
            "rustc --version",
        ]
    return commands


async def _prepare_repo() -> dict[str, Any]:
    """Make the staged source a git repo, install its dependencies, snapshot it for the graders.

    A zip with its ``.git`` inside keeps its history (vaulted at setup like
    any other flavor); plain source gets one root commit. Setup runs as root
    before the chown: ``setup.sh`` from the pack (the RUN lines the task's
    Dockerfile used to have) or the manifest auto-detection; a non-zero exit
    fails the task closed. ``$GRADER_DIR/base`` is then the repo exactly as
    the agent receives it (dependencies installed, no ``.git``) - the
    pre-change tree for run_grading.sh and for the judge.
    """
    # Hosted: Workspace.start() has already chowned REPO_DIR to the agent uid,
    # so root's git sees dubious ownership. safe.directory must be set before
    # any git that touches the worktree (init/add), not after. Global config
    # only: git ignores -c for this check.
    if _is_root():
        await repo_lib.run("git", "config", "--global", "--add", "safe.directory", str(REPO_DIR), cwd=Path("/"))
    if not (REPO_DIR / ".git").exists():
        await repo_lib.git(REPO_DIR, "init", "-q", "-b", "main", ".")
        await repo_lib.git(REPO_DIR, "add", "-A")
        await repo_lib.git(REPO_DIR, "commit", "-q", "--allow-empty", "-m", "baseline")
    _, sha, _ = await repo_lib.git(REPO_DIR, "rev-parse", "HEAD")
    base_sha = sha.strip()

    script = GRADER_DIR / "setup.sh"
    mode, commands = ("script", [f"bash {script}"]) if script.is_file() else ("auto", setup_commands(REPO_DIR))
    log = LOGS_DIR / "setup.log"
    loop = asyncio.get_event_loop()
    deadline = loop.time() + SETUP_TIMEOUT
    for command in commands:
        rc, out = await _sh(command, cwd=REPO_DIR, timeout=max(1.0, deadline - loop.time()), log=log)
        if rc != 0:
            raise TaskSetupError("setup_failed", mode=mode, command=command, exit_code=rc, log_tail=out[-3000:])

    base = GRADER_DIR / "base"
    shutil.rmtree(base, ignore_errors=True)
    await repo_lib.run("cp", "-a", str(REPO_DIR), str(base), cwd=Path("/"), timeout=1200.0)
    shutil.rmtree(base / ".git", ignore_errors=True)
    (GRADER_DIR / "base_sha").write_text(base_sha + "\n", "utf-8")
    return {"base_sha": base_sha, "setup": mode, "commands": commands}


async def _lock_down() -> None:
    """Root owns /hud at mode 700; the agent owns the toolchain caches setup filled.

    HUD_TOOLCHAIN_CACHES (Dockerfile.hud) lists them: Go module and build
    caches, fnm's Node versions, corepack, the pnpm store, uv's interpreters
    and cache, rustup. Warm from setup, and writable so the agent can add a
    dependency or a toolchain; the grader runs as root and reads them fine.
    """
    if not _is_root():
        return
    await repo_lib.run("chown", "-R", "root:root", str(HUD_ROOT), cwd=Path("/"), timeout=1200.0)
    for path in (HUD_ROOT, GRADER_DIR, LOGS_DIR, VAULT_DIR):
        if path.exists():
            path.chmod(0o700)
    caches = [p for p in os.environ.get("HUD_TOOLCHAIN_CACHES", "").split(":") if p and Path(p).is_dir()]
    if caches:
        await repo_lib.run("chown", "-R", f"{AGENT_UID}:{AGENT_UID}", *caches, cwd=Path("/"), timeout=1200.0)


async def _start_services() -> None:
    """services.sh must start its daemons and return once they answer."""
    script = GRADER_DIR / "services.sh"
    if not script.is_file():
        return
    rc, out = await _sh(
        f"bash {script}", cwd=GRADER_DIR, timeout=300.0, log=LOGS_DIR / "services.log", new_session=True
    )
    if rc != 0:
        raise TaskSetupError("services_failed", exit_code=rc, log_tail=out[-3000:])


# ─── swe-task grading ────────────────────────────────────────────────────


async def _bash_row(name: str, row: CriterionRow, setup_commit: str, diff: str) -> tuple[SubScore, bool]:
    """``bash run_grading.sh <id>``: exit 0 is the verdict; GRADER_SCORE makes the value fractional."""
    if row.pristine_paths:
        # The baseline's own copies, so an edited assertion cannot buy a pass.
        await repo_lib.git(REPO_DIR, "checkout", setup_commit, "--", *row.pristine_paths, check=False)
    rc, out = await _sh(
        f"bash {GRADER_DIR / GRADER_SCRIPT} {name}", cwd=REPO_DIR, timeout=row.timeout, log=LOGS_DIR / "grading.log"
    )
    if row.pristine_paths:
        await repo_lib.reset_worktree(REPO_DIR, setup_commit)
        await repo_lib.apply_diff(REPO_DIR, diff, LOGS_DIR / "patch.diff")
    passed = rc == 0
    value = 1.0 if passed else 0.0
    if fractions := _SCORE_LINE.findall(out):
        value = max(0.0, min(1.0, float(fractions[-1])))
    info = {
        "statement": row.statement,
        "weight_points": row.weight,
        "blocker": row.blocker,
        "gate": row.gate,
        "verdict": "PASS" if passed else "FAIL",
        "exit_code": rc,
        "output_tail": out[-2500:],
    }
    return SubScore(name=name, weight=row.weight, value=value, info=info), passed


async def _judge_row(name: str, row: RubricRow, prompt: str, diff: str, inspector: judge_lib.Inspector) -> SubScore:
    if row.tools or row.negative:
        return await judge_lib.judge_row(
            row, name=name, prompt=prompt, diff=diff, inspector=inspector if row.tools else None
        )
    # The cheap path: one native judge call over the summary (never the raw diff).
    summary, _ = judge_lib.diff_summary(diff)
    criteria = [row.statement] + ([f"Guidance for the reviewer: {row.guidance}"] if row.guidance else [])
    try:
        score = await LLMJudgeGrader.grade(
            row.weight,
            name=name,
            answer=summary,
            criteria=criteria,
            question=f"Does this code change satisfy the following requirement? {row.statement}",
            model=row.model or "claude-haiku-4-5",
        )
    except Exception as exc:  # noqa: BLE001 - fail closed at full weight
        score = SubScore(
            name=name, weight=row.weight, value=0.0, info={"judge_error": f"{type(exc).__name__}: {exc}"[:300]}
        )
    info = {**(score.info or {}), "statement": row.statement, "weight_points": row.weight, "judge": "diff-summary only"}
    return score.model_copy(update={"info": info})


async def _grade_swe(
    validate_mode: str | None, criteria: list[CriterionRow], rubric: list[RubricRow], prompt: str
) -> EvaluationResult:
    setup_commit = await repo_lib.restore_history(REPO_DIR, VAULT_DIR)
    if validate_mode is None:
        diff = await repo_lib.capture_agent_diff(REPO_DIR, setup_commit)
    else:
        # "golden" grades the uploaded gold.diff; any other name is a probe
        # diff shipped in the grading pack (maintainer calibration).
        reference = GOLD_PATH if validate_mode == "golden" else GRADER_DIR / f"{validate_mode}.diff"
        if not reference.is_file():
            return _zero("missing_reference_diff", validate_mode=validate_mode)
        diff = reference.read_text("utf-8")
    if not diff.strip():
        return EvaluationResult(reward=0.0, content="Empty diff: no changes were made.")
    await repo_lib.reset_worktree(REPO_DIR, setup_commit)
    apply_error = await repo_lib.apply_diff(REPO_DIR, diff, LOGS_DIR / "patch.diff")
    if apply_error is not None:
        return EvaluationResult(reward=0.0, content="patch failed to apply", info={"git_apply": apply_error})

    # The judge reads a root-owned copy of the agent's final tree, taken
    # before any grader touches the worktree, plus the pre-change tree.
    snapshot = LOGS_DIR / "judge-snapshot"
    inspector = None
    if rubric:
        shutil.rmtree(snapshot, ignore_errors=True)
        await repo_lib.run("cp", "-a", str(REPO_DIR), str(snapshot), cwd=Path("/"), timeout=1200.0)
        shutil.rmtree(snapshot / ".git", ignore_errors=True)
        inspector = judge_lib.Inspector(snapshot, GRADER_DIR / "base", diff)

    os.environ.update(
        {
            "SETUP_COMMIT": setup_commit,
            "BASE_SHA": (GRADER_DIR / "base_sha").read_text().strip(),
            "AGENT_DIFF": str(LOGS_DIR / "patch.diff"),
        }
    )
    # The judge goes first: it reads the snapshot and $GRADER_DIR/base, and a
    # grading script may sync the agent's sources into base for its own runs.
    judged = [
        await _judge_row(criterion_id(row, index), row, prompt, diff, inspector)  # type: ignore[arg-type]
        for index, row in enumerate(rubric, start=1)
    ]
    named = [(criterion_id(row, index), row) for index, row in enumerate(criteria, start=1)]
    # Gates first (the ticket's preconditions, before anything touched the
    # tree), then the weighted rows in table order. Sequential: hidden suites
    # are often timing-sensitive and share state under GRADER_STATE_DIR.
    weighted: list[SubScore] = []
    gates: list[SubScore] = []
    failed_blockers: list[str] = []
    failed_gates: list[str] = []
    for name, row in sorted(named, key=lambda item: 0 if item[1].gate else 1):
        score, passed = await _bash_row(name, row, setup_commit, diff)
        if row.gate:
            gates.append(score)
            if not passed:
                failed_gates.append(name)
        else:
            weighted.append(score)
            if row.blocker and not passed:
                failed_blockers.append(name)
    weighted.extend(judged)

    result = await combine(*weighted)
    uncapped = result.reward
    reward = uncapped * BLOCKER_SCALE if failed_blockers else uncapped
    if failed_gates:
        reward = min(reward, uncapped * GATE_SCALE)
    reward = max(0.0, min(1.0, reward))

    lines = [f"reward {reward:.3f} (uncapped {uncapped:.3f})"]
    if failed_blockers:
        lines.append(f"blockers failed ({', '.join(failed_blockers)}): reward = uncapped x {BLOCKER_SCALE:.3f}")
    if failed_gates:
        lines.append(f"gates failed ({', '.join(failed_gates)}): reward capped at uncapped x {GATE_SCALE:.1f}")
    for score in gates:
        lines.append(f"gate {score.name}: {(score.info or {}).get('verdict')}")
    for score in weighted:
        lines.append(f"{score.name}: {score.value:.3f} x {(score.info or {}).get('weight_points', score.weight):.2f}")
    _, file_stats = judge_lib.diff_summary(diff)
    info: dict[str, Any] = {
        **(result.info or {}),
        "uncapped_reward": uncapped,
        "failed_blockers": failed_blockers,
        "failed_gates": failed_gates,
        "blocker_scale": BLOCKER_SCALE,
        "gate_scale": GATE_SCALE,
        "changed_files": file_stats[:200],
    }
    with warnings.catch_warnings():
        # The reward is the capped weighted sum on purpose; the model warns when they differ.
        warnings.simplefilter("ignore")
        return EvaluationResult(
            reward=reward, subscores=[*result.subscores, *gates], info=info, content="\n".join(lines)
        )


@env.template(
    id="swe-task",
    description="A coding task from uploads: the codebase zip, the grading zip "
    "(run_grading.sh + criteria.json + tests, optional setup.sh/services.sh), "
    "an optional gold.diff and an optional llm_rubric.json. Nothing is baked in.",
)
async def swe_task(
    prompt: Prompt,
    codebase: Upload,
    grading: Upload,
    golden_solution: OptionalUpload = None,
    llm_rubric: OptionalUpload = None,
    # Declaring this argument is what makes the platform deliver the key to a
    # hosted run (the console hides it). It downloads the uploads and pays
    # for the judge through the HUD gateway.
    hud_api_key: str | None = None,
    validate_mode: str | None = None,
):
    """One coding task; everything graded arrives in the uploads.

    Stage the files, prepare the repo (``setup.sh`` from the grading pack,
    else auto-detection from the repo's manifests), start ``services.sh`` if present, hand
    the agent the prompt; then ``run_grading.sh <id>`` for every row of
    ``criteria.json`` and one judge run per row of ``llm_rubric.json``,
    combined into one result. ``validate_mode="golden"`` grades the uploaded
    ``gold.diff`` instead of agent work.
    """
    if hud_api_key:
        os.environ["HUD_API_KEY"] = hud_api_key
        settings.api_key = hud_api_key
    try:
        codebase_ref, grading_ref = _upload(codebase), _upload(grading)
        gold_ref, rubric_ref = _upload(golden_solution), _upload(llm_rubric)
        if codebase_ref is None or grading_ref is None:
            raise ValueError("codebase and grading uploads are required")
        if validate_mode == "golden" and gold_ref is None:
            raise ValueError('validate_mode="golden" needs a golden_solution upload')
    except Exception as exc:  # noqa: BLE001 - fail closed: a misconfigured task scores 0
        # First yield is the agent prompt; a grade frame here is rendered as
        # the field names ("reward / done / content / …"). Prompt, then grade.
        _ = yield _failed_prompt("invalid_task_args")
        yield _zero("invalid_task_args", reason=str(exc)[:800])
        return

    setup_info: dict[str, Any] = {}
    try:
        await _stage_uploads(codebase_ref, grading_ref, gold_ref, rubric_ref, hud_api_key)
        try:
            criteria = load_criteria(GRADER_DIR)
            rubric = load_rubric(RUBRIC_PATH) if rubric_ref is not None else []
            names = [criterion_id(r, i) for i, r in enumerate(criteria, 1)] + [
                criterion_id(r, i) for i, r in enumerate(rubric, 1)
            ]
            if len(set(names)) != len(names):
                raise ValueError("criteria.json and llm_rubric.json share ids")
        except Exception as exc:  # noqa: BLE001
            raise TaskSetupError("invalid_grading_pack", reason=str(exc)[:800]) from exc
        setup_info = await _prepare_repo()
        await _lock_down()
        await _setup()
        await _start_services()
    except TaskSetupError as exc:
        _stop_services()
        _ = yield _failed_prompt(exc.status)
        yield _zero(exc.status, **exc.info)
        return
    except Exception as exc:  # noqa: BLE001 - anything else is still a task that cannot run
        _stop_services()
        _ = yield _failed_prompt("setup_error")
        yield _zero("setup_error", reason=repr(exc)[:800])
        return

    if validate_mode is not None:
        _ = yield "Validation run: no work is expected of you. Finish immediately."
    else:
        # Bullet + "Prompt:" so the harness line does not collapse into the
        # ticket wherever the viewer renders the yield as markdown.
        _ = yield f"- {WORKSPACE_NOTE}\n\nPrompt:\n{prompt}"

    try:
        result = await _grade_swe(validate_mode, criteria, rubric, prompt)
    except Exception as exc:  # noqa: BLE001 - fail closed
        result = _zero("grader_error", reason=repr(exc)[:800])
    finally:
        _stop_services()
    result.info.setdefault("setup", setup_info)
    yield result


# ─── generic flavor (git refs in a baked or cloned repo) ─────────────────


async def _grade_generic(
    test_command: str,
    base_ref: str | None,
    test_ref: str | None,
    test_files: list[str] | None,
    golden_ref: str | None,
    validate_mode: str | None,
) -> EvaluationResult:
    setup_commit = await repo_lib.restore_history(REPO_DIR, VAULT_DIR)
    if validate_mode == "golden":
        if not (base_ref and golden_ref):
            raise ValueError('validate_mode="golden" needs base_ref and golden_ref')
        _, diff, _ = await repo_lib.git(REPO_DIR, "diff", base_ref, golden_ref)
    else:
        diff = await repo_lib.capture_agent_diff(REPO_DIR, setup_commit)

    await repo_lib.reset_worktree(REPO_DIR, setup_commit)
    apply_error = await repo_lib.apply_diff(REPO_DIR, diff, LOGS_DIR / "patch.diff")
    if apply_error is not None:
        return EvaluationResult(reward=0.0, content="patch failed to apply", info={"git_apply": apply_error})
    if test_ref:
        # Hidden tests come from the vaulted history, after the agent's diff —
        # so agent edits to them never survive into grading.
        await repo_lib.git(REPO_DIR, "checkout", test_ref, "--", *(test_files or ["."]))

    command = test_command.format(test_files=" ".join(test_files or []))
    return await combine(
        BashGrader.grade(weight=1.0, command=command, cwd=str(REPO_DIR), timeout_seconds=int(TESTS_TIMEOUT))
    )


@env.template(id="coding-task", description="Fix a bug in the repo; hidden tests grade the diff.")
async def coding_task(
    description: Prompt,
    test_command: str,
    base_ref: str | None = None,
    test_ref: str | None = None,
    test_files: list[str] | None = None,
    golden_ref: str | None = None,
    validate_mode: str | None = None,
    hud_api_key: str | None = None,
):
    """Generic coding task.

    ``base_ref`` is the agent's starting state; ``test_ref`` holds the hidden
    tests (``test_files`` are checked out from it at grade time);
    ``test_command`` scores by exit code, with ``{test_files}`` expanded.
    ``validate_mode="golden"`` grades ``base_ref..golden_ref`` instead of
    agent edits.
    """
    if validate_mode not in (None, "golden"):
        raise ValueError(f"unknown validate_mode: {validate_mode!r}")
    _ = hud_api_key  # declared so hosted runs inject HUD_API_KEY; unused here
    await _setup(base_ref)
    _ = yield (
        f"You are working in a coding repository located at {REPO_DIR}. {WORKSPACE_NOTE}\n\n"
        "Use the tools provided to complete the following task. Hidden tests grade your "
        f"work when you finish; do not modify existing tests.\n\n{description}"
    )
    yield await _grade_generic(test_command, base_ref, test_ref, test_files, golden_ref, validate_mode)


# ─── SDLC flavor: issue-driven fix, graded on the pushed PR branch ───────


async def _fetch_hidden_ref(dest: Path, ref: str) -> None:
    """Fetch an answer-key ref from the vaulted history into *dest*."""
    full = f"refs/remotes/{ref}" if ref.startswith("origin/") else ref
    await repo_lib.git(dest, "fetch", "-q", str(VAULT_DIR / "git"), full)


async def _grade_sdlc(
    test_command: str,
    test_ref: str,
    test_files: list[str],
    golden_ref: str | None,
    pr_rubric: str | None,
    validate_mode: str | None,
) -> EvaluationResult:
    if validate_mode == "golden":
        # Simulate the workflow the agent is graded on: push the reference
        # fix as a branch and open a pull request for it.
        if not golden_ref:
            raise ValueError('validate_mode="golden" needs golden_ref')
        await repo_lib.git(VAULT_DIR / "git", "push", "-q", str(REMOTE_DIR), f"{golden_ref}:refs/heads/golden-fix")
        _github.create_pull_request(
            "Fix the reported bug", "Applies the reference fix.", head="golden-fix", base="main"
        )

    pr = _github.latest_pull_request()
    if pr is None:
        return EvaluationResult(reward=0.0, content="no pull request was opened")

    # Hermetic checkout of the PR head from the remote (never the worktree).
    grading_dir = LOGS_DIR / "pr-checkout"
    shutil.rmtree(grading_dir, ignore_errors=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    await repo_lib.run("git", "clone", "-q", str(REMOTE_DIR), str(grading_dir), cwd=LOGS_DIR)
    code, _, err = await repo_lib.git(grading_dir, "checkout", "-q", pr.head, check=False)
    if code != 0:
        return EvaluationResult(
            reward=0.0,
            content=f"pull request head branch {pr.head!r} was never pushed",
            info={"git_checkout": err.strip()[-2000:]},
        )

    await _fetch_hidden_ref(grading_dir, test_ref)
    await repo_lib.git(grading_dir, "checkout", "FETCH_HEAD", "--", *test_files)

    command = test_command.format(test_files=" ".join(test_files))
    quality: Any
    if pr_rubric:
        quality = LLMJudgeGrader.grade(weight=0.2, answer=_github.transcript(), criteria=[pr_rubric])
    else:
        opened_well = bool(pr.title.strip() and pr.body.strip())
        quality = SubScore(name="pull_request", value=1.0 if opened_well else 0.0, weight=0.2)
    return await combine(
        BashGrader.grade(weight=0.8, command=command, cwd=str(grading_dir), timeout_seconds=int(TESTS_TIMEOUT)),
        quality,
    )


@env.template(
    id="sdlc-task",
    description="Issue-driven bug fix: fix the code, push a branch, open a pull request.",
)
async def sdlc_task(
    description: Prompt,
    test_command: str,
    base_ref: str,
    test_ref: str,
    test_files: list[str],
    issues: list[dict[str, Any]] | None = None,
    golden_ref: str | None = None,
    pr_rubric: str | None = None,
    validate_mode: str | None = None,
    hud_api_key: str | None = None,
):
    """The generic flavor plus workflow: the repo has an ``origin`` remote (a
    bare mock-GitHub repo) and ``github_*`` tools seeded with *issues*; the
    deliverable is a pushed branch with a pull request. Grading checks the PR
    head out of the remote, brings in the hidden tests, runs ``test_command``
    (weight 0.8), and scores the PR itself (weight 0.2) — structurally, or
    against ``pr_rubric`` with an LLM judge when provided.
    """
    if validate_mode not in (None, "golden"):
        raise ValueError(f"unknown validate_mode: {validate_mode!r}")
    if hud_api_key:
        os.environ["HUD_API_KEY"] = hud_api_key
    _github.seed(issues or [])
    await _setup(base_ref, remote=True)
    _ = yield (
        f"You are working in a coding repository located at {REPO_DIR}; its `origin` remote "
        "is the team's shared repository, and the `github_*` tools give you the team's "
        "issue tracker.\n\n"
        "Complete the following task. When you are done, push your work to `origin` as a "
        "new branch and open a pull request for it with `github_create_pull_request`. "
        "Hidden tests grade your work; do not modify existing tests.\n\n"
        f"{description}"
    )
    yield await _grade_sdlc(test_command, test_ref, test_files, golden_ref, pr_rubric, validate_mode)


# ─── SWE-bench Pro flavor (present only in baked instance images) ────────

if (INSTANCE_DIR / "instance.json").is_file():
    INSTANCE = swe.load_instance(INSTANCE_DIR)

    @env.template(
        id=INSTANCE["instance_id"],
        description=f"SWE-bench Pro instance on {INSTANCE['repo']}",
    )
    async def swe_bench_pro_task(validate_mode: str | None = None):
        """One SWE-bench Pro rollout. ``validate_mode="golden"`` grades the
        dataset's golden patch instead of agent edits (gold-patch validation)."""
        if validate_mode not in (None, "golden"):
            raise ValueError(f"unknown validate_mode: {validate_mode!r}")
        await _setup()
        _ = yield swe.build_prompt(INSTANCE, REPO_DIR)
        yield await swe.grade(
            INSTANCE,
            INSTANCE_DIR,
            REPO_DIR,
            VAULT_DIR,
            LOGS_DIR,
            validate_mode=validate_mode,
            tests_timeout=TESTS_TIMEOUT,
        )
