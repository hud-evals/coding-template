"""fix_aggregate_listing (Justin Menga) on the coding-template.

Reads like a scoreboard:

- GRADERS is the single list of ALL criteria: (name, weight, blocker, kind,
  timeout). "bash" entries map to a function in task/grader/run_grading.sh
  (and the hidden test it runs); the "judge" entry is the LLM diff review
  whose criteria live in task/grader/judge.json. The subscore you see in
  the trace viewer is the name you grep for in the grader.
- The task template runs them sequentially over the coding-template's
  hermetic repo lifecycle (vault -> capture diff -> reset -> re-apply).

``validate_mode="golden"`` grades the baked /hud/gold.diff instead of the
agent's edits (maintainer-only gold validation).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from hud.graders import BashGrader, EvaluationResult, LLMJudgeGrader, SubScore, combine

from coding import repo as repo_lib
from env import LOGS_DIR, REPO_DIR, VAULT_DIR, env, _setup

PROMPT = (Path(__file__).parent / "task" / "prompt.md").read_text()
GRADER = "/hud/grader/run_grading.sh"
GOLD_DIFF = Path("/hud/gold.diff")
# On blocker failure: reward = min(uncapped, BLOCKER_CAP + 0.5 * uncapped).
BLOCKER_CAP = 0.2

# ─── ALL graders: name, weight, blocker?, kind, timeout ───────────────────
# "bash" graders: name == function in run_grading.sh == hidden test it runs.
# "judge": the LLM diff review; its criteria live in task/grader/judge.json.

GRADERS = [
    ("ordering_equivalence",   0.20, True,  "bash",   900),
    ("pagination_invariants",  0.20, True,  "bash",   900),
    ("throughput_discipline",  0.10, True,  "bash",   900),
    ("n_plus_one",             0.10, False, "bash",   600),
    ("regression_backcompat",  0.15, True,  "bash",  1800),
    ("test_quality",           0.15, True,  "bash",  1800),
    ("conventions_gates",      0.05, False, "bash",   900),
    ("maintainer_review",      0.05, False, "judge", None),
]

# The judge's question/criteria live with the other graders, in a file named
# after its criterion: task/grader/<name>.judge.json. Only the API call
# happens here, because it needs the captured diff and env-side credentials.
_JUDGE_FILE = "maintainer_review.judge.json"
_GRADER_SRC = Path(os.environ.get("GRADER_DIR", "/hud/grader"))
if not (_GRADER_SRC / _JUDGE_FILE).is_file():  # local dev, outside the image
    _GRADER_SRC = Path(__file__).parent / "task" / "grader"
JUDGE = json.loads((_GRADER_SRC / _JUDGE_FILE).read_text())

# ─── substrate sidecar: DynamoDB Local on 127.0.0.1:8000 ─────────────────

_DDB_JAR = Path("/opt/dynamodb-local/DynamoDBLocal.jar")
_ddb_proc: subprocess.Popen | None = None


@env.initialize
async def _start_dynamodb() -> None:
    """Spawn DynamoDB Local WITHOUT waiting for readiness.

    Only grading needs it, so readiness is awaited in _grade(); blocking here
    would delay the serve port past the platform's 60s introspection probe.
    """
    global _ddb_proc
    if not _DDB_JAR.is_file():
        return  # grading needs the image; local runs skip the sidecar
    _ddb_proc = subprocess.Popen(
        [
            "java",
            "-Djava.library.path=/opt/dynamodb-local/DynamoDBLocalLib",
            "-jar", str(_DDB_JAR),
            "-inMemory", "-port", "8000",
        ],
        cwd="/opt/dynamodb-local",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _await_dynamodb(timeout: float = 120.0) -> None:
    if _ddb_proc is None:
        return  # local substrate without the sidecar
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", 8000)
            writer.close()
            return
        except OSError:
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError("DynamoDB Local did not become ready") from None
            await asyncio.sleep(0.25)


@env.shutdown
async def _stop_dynamodb() -> None:
    global _ddb_proc
    if _ddb_proc is not None:
        _ddb_proc.terminate()
        _ddb_proc = None


# ─── grading machinery ─────────────────────────────────────────────────────


def _slim_metadata(subscores) -> None:
    """Bound subscore metadata so the grade frame stays small."""
    for score in subscores:
        meta = getattr(score, "metadata", None)
        if not meta:
            continue
        params = meta.get("_parameters")
        if isinstance(params, dict):
            for key in ("answer", "question"):
                if key in params and isinstance(params[key], str) and len(params[key]) > 300:
                    params[key] = f"({key} elided; {len(params[key])} chars)"
        for key in ("stdout", "stderr"):
            value = meta.get(key)
            if isinstance(value, str) and len(value) > 2500:
                meta[key] = "…" + value[-2500:]


async def _judge_diff(name: str, weight: float, diff: str) -> SubScore:
    try:
        return await LLMJudgeGrader.grade(
            weight,
            name=name,
            answer=diff[:100_000],
            criteria=list(JUDGE["criteria"]),
            question=JUDGE["question"],
        )
    except Exception as exc:  # noqa: BLE001 - judge failure must not kill grading
        return SubScore(
            name=name, weight=0.0, value=0.0,
            metadata={"judge_error": f"{type(exc).__name__}: {exc}"[:300]},
        )


async def _grade(validate_mode: str | None) -> EvaluationResult:
    # The connected hidden tests need the DynamoDB Local sidecar (spawned at
    # initialize without blocking; awaited here where it's actually used).
    await _await_dynamodb()

    # Hermetic lifecycle: restore the vaulted history, capture the diff,
    # reset the worktree, re-apply the diff — then grade that state.
    setup_commit = await repo_lib.restore_history(REPO_DIR, VAULT_DIR)
    if validate_mode == "golden":
        diff = GOLD_DIFF.read_text()
    else:
        diff = await repo_lib.capture_agent_diff(REPO_DIR, setup_commit)

    if not diff.strip():
        return EvaluationResult(reward=0.0, content="Empty diff: no changes were made.")

    await repo_lib.reset_worktree(REPO_DIR, setup_commit)
    apply_error = await repo_lib.apply_diff(REPO_DIR, diff, LOGS_DIR / "patch.diff")
    if apply_error is not None:
        return EvaluationResult(
            reward=0.0, content="patch failed to apply", info={"git_apply": apply_error}
        )

    # One grader call per criterion, SEQUENTIAL (the bash ones share the
    # runner tree). Subscore name == grader function name == hidden test.
    subscores: list[SubScore] = []
    for name, weight, _blocker, kind, timeout in GRADERS:
        if kind == "bash":
            subscores.append(
                await BashGrader.grade(
                    weight,
                    name=name,
                    command=f"bash {GRADER} {name}",
                    cwd=str(REPO_DIR),
                    timeout_seconds=timeout,
                )
            )
        else:
            subscores.append(await _judge_diff(name, weight, diff))

    _slim_metadata(subscores)
    result = await combine(*subscores)

    judge_errors = {
        s.name: s.metadata["judge_error"]
        for s in subscores
        if s.metadata and s.metadata.get("judge_error")
    }
    if judge_errors:
        result.info["judge_errors"] = judge_errors

    failed = sorted(
        name for name, _w, blocker, _kind, _t in GRADERS
        if blocker and next(s.value for s in subscores if s.name == name) < 1.0
    )
    if failed:
        # Scaled cap: a blocker failure hurts a lot, but better partial work
        # still scores higher than garbage (training signal > flat cap).
        reward = min(result.reward, BLOCKER_CAP + 0.5 * result.reward)
        return EvaluationResult(
            reward=reward,
            subscores=result.subscores,
            info={**result.info, "uncapped_reward": result.reward, "failed_blockers": failed},
            content=(
                f"Blocker criteria failed ({', '.join(failed)}); "
                f"reward scaled down to {reward:.3f} (uncapped {result.reward:.3f})."
            ),
        )
    return result


@env.template(
    id="fix_aggregate_listing",
    description="Make Aggregate.list() scale; sharded listing must match unsharded behavior.",
)
async def fix_aggregate_listing(validate_mode: str | None = None):
    if validate_mode not in (None, "golden"):
        raise ValueError(f"unknown validate_mode: {validate_mode!r}")
    await _setup()
    if validate_mode == "golden":
        # Agent work is ignored; the baked gold.diff gets graded instead.
        _ = yield "Golden-validation run: no work is expected of you. Finish immediately."
    else:
        # prompt.md opens with its own workspace preamble; no template prefix.
        _ = yield PROMPT
    yield await _grade(validate_mode)


tasks = [fix_aggregate_listing()]
