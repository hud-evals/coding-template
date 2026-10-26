"""Regression: agent-injected pytest hooks must not earn reward 1.0."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from grading.runner import GradingRunner

SAMPLE_REPO = Path(os.environ.get(
    "HUD_SAMPLE_REPO",
    Path(__file__).resolve().parents[2] / "sample",
))


@pytest.fixture
def prepared(tmp_path: Path):
    if not SAMPLE_REPO.exists():
        pytest.skip(f"sample repo missing: {SAMPLE_REPO}")
    repo = tmp_path / "project"
    patches = tmp_path / "patches"
    shutil.copytree(SAMPLE_REPO, repo, symlinks=True)
    subprocess.run(
        ["git", "checkout", "-f", "origin/sentry_fix_baseline"],
        cwd=repo, check=True, capture_output=True,
    )
    (patches / "sentry_fix").mkdir(parents=True)
    diff = subprocess.run(
        ["git", "diff", "origin/sentry_fix_baseline", "origin/sentry_fix_test"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    (patches / "sentry_fix" / "test.patch").write_text(diff.stdout)
    return repo, patches


def _score(repo: Path, patches: Path) -> float:
    return GradingRunner(
        problem_id="sentry_fix",
        test_command="pytest {test_files}",
        test_files=["test_user_service.py"],
        patches_dir=str(patches),
        repo_path=str(repo),
    ).grade()


def test_buggy_baseline_scores_zero(prepared):
    repo, patches = prepared
    assert _score(repo, patches) == 0.0


def test_golden_scores_one(prepared):
    repo, patches = prepared
    subprocess.run(
        ["git", "checkout", "-f", "origin/sentry_fix_golden"],
        cwd=repo, check=True, capture_output=True,
    )
    assert _score(repo, patches) == 1.0


def test_conftest_skip_all_scores_zero(prepared):
    repo, patches = prepared
    (repo / "conftest.py").write_text(
        "import pytest\n"
        "def pytest_runtest_setup(item):\n"
        "    pytest.skip('reward hack')\n"
    )
    assert _score(repo, patches) == 0.0


def test_conftest_force_exitstatus_scores_zero(prepared):
    repo, patches = prepared
    (repo / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 0\n"
    )
    assert _score(repo, patches) == 0.0
