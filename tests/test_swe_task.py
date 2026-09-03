"""swe-task without Docker or network: the tables, the staging, the grading loop, the judge, the packager."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import env as env_module
from coding import judge, uploads
from coding import repo as repo_lib

# ─── criteria.json / llm_rubric.json ─────────────────────────────────────


def test_criteria_rows_take_requirement_and_gates_carry_no_weight():
    rows = uploads.parse_criteria(
        [
            {"id": "unit", "requirement": "hidden unit tests pass", "weight": 0.7, "blocker": True},
            {"requirement": "Lint is clean", "weight": 0.3},
            {"id": "anti_hack_gate", "requirement": "no test weakened", "gate": True, "weight": 0.5},
        ]
    )
    assert [uploads.criterion_id(r, i) for i, r in enumerate(rows, 1)] == ["unit", "lint_is_clean", "anti_hack_gate"]
    assert rows[2].gate and rows[2].weight == 0.0
    assert rows[0].statement == "hidden unit tests pass"


def test_criteria_rejects_duplicates_unknown_keys_and_weightless_tables():
    with pytest.raises(ValueError, match="duplicate"):
        uploads.parse_criteria([{"id": "a", "requirement": "x"}, {"id": "a", "requirement": "y"}])
    with pytest.raises(ValueError):
        uploads.parse_criteria([{"id": "a", "requirement": "x", "kind": "bash"}])
    with pytest.raises(ValueError, match="no row carries weight"):
        uploads.parse_criteria([{"id": "g", "requirement": "x", "gate": True}])


def test_rubric_rows_share_the_shape_and_add_judge_switches():
    rows = uploads.parse_rubric(
        [
            {"id": "idioms", "requirement": "Follows Effect idioms", "weight": 0.05, "guidance": "biome style"},
            {
                "id": "no_sleep",
                "requirement": "Uses a sleep to hide a race",
                "weight": 0.1,
                "negative": True,
                "tools": False,
            },
        ]
    )
    assert rows[0].tools and not rows[0].negative
    assert rows[1].negative and not rows[1].tools


# ─── staging ─────────────────────────────────────────────────────────────


def test_destination_refuses_escapes(tmp_path):
    for bad in ("../x", "/abs", "a/../../b", ""):
        with pytest.raises(uploads.DataFileError):
            uploads.destination(tmp_path, bad)
    assert uploads.destination(tmp_path, "a/b.txt") == tmp_path / "a" / "b.txt"


def test_expand_zip_keeps_modes_strips_wrapper_and_rejects_escaping_symlinks(tmp_path):
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("repo-main/run.sh")
        info.external_attr = 0o100755 << 16
        zf.writestr(info, "#!/bin/sh\n")
        zf.writestr("repo-main/src/a.txt", "a")
    root = tmp_path / "out"
    uploads.expand_zip(archive, root)
    assert (root / "run.sh").is_file() and os.access(root / "run.sh", os.X_OK)
    assert (root / "src" / "a.txt").read_text() == "a"
    assert not archive.exists()

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        link = zipfile.ZipInfo("key")
        link.external_attr = (0o120777) << 16
        zf.writestr(link, "../../hud/gold.diff")
    with pytest.raises(uploads.DataFileError, match="escapes"):
        uploads.expand_zip(evil, tmp_path / "out2")


def test_upload_argument_accepts_id_object_or_single_item_list():
    assert env_module._upload("f1").file_id == "f1"
    assert env_module._upload({"file_id": "f2"}).file_id == "f2"
    assert env_module._upload([{"file_id": "f3"}]).file_id == "f3"
    assert env_module._upload(None) is None
    with pytest.raises(ValueError):
        env_module._upload([{"file_id": "a"}, {"file_id": "b"}])


def test_setup_auto_detection_reads_lockfiles(tmp_path):
    assert env_module.setup_commands(tmp_path) == []
    (tmp_path / "pnpm-lock.yaml").write_text("")
    (tmp_path / "go.mod").write_text("module x\n")
    assert env_module.setup_commands(tmp_path) == ["pnpm install --frozen-lockfile", "go mod download"]


# ─── the grading loop, end to end on a throwaway repo ─────────────────────

GRADING_SH = """#!/usr/bin/env bash
set -u
REPO=${REPO_DIR:?}
G=${GRADER_DIR:?}
hidden_test() { grep -q "return 42" "$REPO/answer.py"; }
half_credit() { echo "GRADER_SCORE 0.5"; return 1; }
lint() { [ -f "$G/base/answer.py" ] && [ -n "$AGENT_DIFF" ] && [ -f "$AGENT_DIFF" ]; }
pristine_probe() { grep -q "original" "$REPO/probe.txt"; }
no_tamper_gate() { ! grep -q "tamper" "$REPO/answer.py"; }
name="${1:-}"
if declare -F "$name" >/dev/null; then "$name"; exit $?; fi
echo "unknown criterion $name" >&2; exit 2
"""

CRITERIA = [
    {"id": "hidden_test", "requirement": "answer() returns 42", "weight": 0.5, "blocker": True},
    {"id": "half_credit", "requirement": "partial via GRADER_SCORE", "weight": 0.3},
    {"id": "lint", "requirement": "grader sees base tree and diff", "weight": 0.2},
    {
        "id": "pristine_probe",
        "requirement": "runs against the baseline's probe.txt",
        "weight": 0.0,
        "pristine_paths": ["probe.txt"],
    },
    {"id": "no_tamper_gate", "requirement": "no tamper marker", "gate": True},
]


@pytest.fixture
def staged_task(tmp_path, monkeypatch):
    """A codebase and a grading pack already 'staged', as _stage_uploads would leave them."""
    repo, grader, logs, vault = (tmp_path / n for n in ("repo", "hud/grader", "hud/logs", "hud/vault"))
    for path in (repo, grader, logs, vault.parent):
        path.mkdir(parents=True, exist_ok=True)
    (repo / "answer.py").write_text("def answer():\n    return 41\n")
    (repo / "probe.txt").write_text("original\n")
    (grader / "run_grading.sh").write_text(GRADING_SH)
    (grader / "criteria.json").write_text(json.dumps(CRITERIA))
    for name, value in (("REPO_DIR", repo), ("GRADER_DIR", grader), ("LOGS_DIR", logs), ("VAULT_DIR", vault)):
        monkeypatch.setattr(env_module, name, value)
    monkeypatch.setattr(env_module, "HUD_ROOT", grader.parent)
    monkeypatch.setattr(env_module, "GOLD_PATH", grader.parent / "gold.diff")
    monkeypatch.setattr(env_module, "AGENT_HOME", tmp_path / "home")
    return repo, grader


async def _bring_up(repo: Path) -> None:
    info = await env_module._prepare_repo()
    assert info["setup"] == "auto" and info["commands"] == []
    await env_module._setup()


@pytest.mark.asyncio
async def test_grading_loop_scores_rows_gates_and_caps(staged_task):
    repo, grader = staged_task
    await _bring_up(repo)
    assert (grader / "base" / "answer.py").read_text().endswith("41\n")
    # The agent's work: fix the answer, edit the probe (which pristine_paths must undo).
    (repo / "answer.py").write_text("def answer():\n    return 42\n")
    (repo / "probe.txt").write_text("edited\n")
    criteria = uploads.load_criteria(grader)

    result = await env_module._grade_swe(None, criteria, [], "prompt")
    by_name = {s.name: s for s in result.subscores}
    assert by_name["hidden_test"].value == 1.0
    assert by_name["half_credit"].value == 0.5
    assert by_name["lint"].value == 1.0
    assert by_name["pristine_probe"].value == 1.0, by_name["pristine_probe"].info
    assert by_name["no_tamper_gate"].info["verdict"] == "PASS"
    assert by_name["hidden_test"].info["statement"] == "answer() returns 42"
    assert by_name["hidden_test"].info["weight_points"] == 0.5
    assert result.reward == pytest.approx(0.5 + 0.15 + 0.2)
    assert result.info["failed_blockers"] == [] and result.info["failed_gates"] == []
    # The worktree is the agent's again after the pristine row.
    assert (repo / "probe.txt").read_text() == "edited\n"


@pytest.mark.asyncio
async def test_failed_blocker_and_gate_scale_the_reward(staged_task):
    repo, grader = staged_task
    await _bring_up(repo)
    (repo / "answer.py").write_text("def answer():\n    return 41  # tamper\n")
    criteria = uploads.load_criteria(grader)
    result = await env_module._grade_swe(None, criteria, [], "prompt")
    uncapped = result.info["uncapped_reward"]
    assert uncapped == pytest.approx(0.15 + 0.2)
    assert result.info["failed_blockers"] == ["hidden_test"]
    assert result.info["failed_gates"] == ["no_tamper_gate"]
    assert result.reward == pytest.approx(min(uncapped / 3, uncapped * 0.2))


@pytest.mark.asyncio
async def test_golden_mode_grades_the_uploaded_gold_diff(staged_task):
    repo, grader = staged_task
    await _bring_up(repo)
    setup_commit = (await repo_lib.git(repo, "rev-parse", "HEAD"))[1].strip()
    (repo / "answer.py").write_text("def answer():\n    return 42\n")
    gold = await repo_lib.capture_agent_diff(repo, setup_commit)
    (repo / "answer.py").write_text("def answer():\n    return 41\n")
    env_module.GOLD_PATH.write_text(gold)
    result = await env_module._grade_swe("golden", uploads.load_criteria(grader), [], "prompt")
    assert {s.name: s.value for s in result.subscores}["hidden_test"] == 1.0


# ─── the judge ───────────────────────────────────────────────────────────

DIFF = """diff --git a/src/app.py b/src/app.py
index 1..2 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 def run():
-    return 1
+    # done: see the summary
+    return 2
diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml
index 1..2 100644
--- a/pnpm-lock.yaml
+++ b/pnpm-lock.yaml
@@ -1 +1,2 @@
-a
+b
+c
diff --git a/src/big.py b/src/big.py
new file mode 100644
--- /dev/null
+++ b/src/big.py
""" + "".join(f"+line {i}\n" for i in range(400))


def test_diff_summary_names_every_file_and_inlines_only_small_hand_written_ones():
    text, stats = judge.diff_summary(DIFF)
    assert "src/app.py  (modified, +2 -1)" in text
    assert "pnpm-lock.yaml  (modified, +2 -1, generated/vendored)" in text
    assert "src/big.py  (added, +400 -0)" in text
    assert "+    return 2" in text  # small file inlined
    assert "+b\n+c" not in text  # lockfile hunks withheld
    assert "+line 399" not in text  # large file withheld
    assert "src/big.py: hunks not shown (400 changed lines)" in text
    assert [s["generated"] for s in stats] == [False, True, False]


@pytest.fixture
def trees(tmp_path):
    snapshot, original = tmp_path / "snap", tmp_path / "orig"
    (snapshot / "src").mkdir(parents=True)
    (original / "src").mkdir(parents=True)
    (snapshot / "src" / "app.py").write_text("\n".join(f"line {i}" for i in range(1, 501)) + "\n")
    (original / "src" / "app.py").write_text("def run():\n    return 1\n")
    (tmp_path / "hud").mkdir()
    (tmp_path / "hud" / "gold.diff").write_text("secret")
    return judge.Inspector(snapshot, original, DIFF)


def test_read_file_pages_with_an_explicit_truncation_marker(trees):
    first = trees.read_file("src/app.py")
    assert first["lines"] == "1-200" and first["total_lines"] == 500
    assert first["truncated"] == "[truncated - 300 more lines, call again with start=201]"
    last = trees.read_file("src/app.py", start=401)
    assert "truncated" not in last and last["content"].endswith("line 500")
    assert trees.files_read == ["src/app.py", "src/app.py"]


def test_tools_stay_inside_the_snapshot(trees):
    for path in ("../hud/gold.diff", "src/../../hud/gold.diff"):
        for tool in (trees.read_file, trees.list_dir, trees.original_file):
            with pytest.raises(ValueError, match="outside"):
                tool(path)
    # An absolute path is read as tree-relative: /hud is the agent tree's own (absent) hud/.
    assert "not a file" in trees.read_file("/hud/gold.diff")["error"]
    assert "not a file" in trees.read_file("/etc/passwd")["error"]
    assert "src/" in trees.list_dir(".")["entries"]
    assert trees.original_file("src/app.py")["content"].startswith("def run()")
    assert trees.diff_for_file("src/app.py")["added"] == 2
    assert "not changed" in trees.diff_for_file("src/none.py")["error"]
    hits = trees.grep(r"line 4\d\d", "src")["matches"]
    assert len(hits) == judge.MAX_MATCHES or all(h.startswith("src/app.py:") for h in hits)


def test_dispatch_reports_calls_remaining_and_survives_bad_input(trees):
    out = json.loads(
        judge.dispatch(trees, "read_file", '{"path": "src/app.py", "start": 1, "end": 3}', calls_remaining=7)
    )
    assert out["calls_remaining"] == 7 and out["lines"] == "1-3"
    assert json.loads(judge.dispatch(trees, "shell", "{}", calls_remaining=6))["error"].startswith("unknown tool")
    assert "error" in json.loads(judge.dispatch(trees, "read_file", "not json", calls_remaining=5))
    assert "error" in json.loads(judge.dispatch(trees, "read_file", '{"nope": 1}', calls_remaining=4))


def test_verdicts_fail_closed():
    positive = {"true_token": "SATISFIED", "false_token": "UNSATISFIED", "require_evidence": False}
    assert judge.parse_verdict("I think it is fine.", **positive)["reason"] == judge.MISSING_REASON
    assert judge.parse_verdict('{"verdict": "maybe"}', **positive)["reason"] == judge.UNUSABLE_REASON
    assert judge.parse_verdict('{"verdict": "false"}', **positive)["fired"] is False
    ok = judge.parse_verdict('```json\n{"verdict": "SATISFIED", "explanation": "' + "x" * 1000 + '"}\n```', **positive)
    assert ok["fired"] and ok["value"] == 1.0 and len(ok["reason"]) == judge.MAX_REASON_CHARS
    negative = {"true_token": "COMMITTED", "false_token": "NOT_COMMITTED", "require_evidence": True}
    quiet = judge.parse_verdict('{"verdict": "COMMITTED", "explanation": "it sleeps"}', **negative)
    assert quiet["fired"] is False and quiet["reason"] == judge.NO_EVIDENCE_REASON
    loud = judge.parse_verdict('{"verdict": "COMMITTED", "evidence": "+    time.sleep(1)"}', **negative)
    assert loud["fired"] and loud["value"] == 1.0
    partial = judge.parse_verdict('{"verdict": "UNSATISFIED", "score": 0.4}', **positive, partial=True)
    assert partial["value"] == 0.4


class FakeLLM:
    """Scripted completions: each entry is either a list of tool calls or a final text."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        step = self.script.pop(0) if self.script else '{"verdict": "UNSATISFIED", "explanation": "out of script"}'
        if isinstance(step, str):
            message = SimpleNamespace(content=step, tool_calls=None)
        else:
            message = SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                    for i, (name, args) in enumerate(step)
                ],
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.asyncio
async def test_judge_loop_uses_tools_then_records_a_verdict(trees):
    row = uploads.RubricRow(id="r", requirement="run() returns 2", weight=0.2)
    llm = FakeLLM(
        [
            [("read_file", {"path": "src/app.py", "end": 2}), ("diff_for_file", {"path": "src/app.py"})],
            '{"verdict": "SATISFIED", "explanation": "return 2 is there", "evidence": "src/app.py:3", "files_verified": ["src/app.py"]}',
        ]
    )
    score = await judge.judge_row(row, name="r", prompt="Make run() return 2", diff=DIFF, inspector=trees, client=llm)
    assert score.value == 1.0 and score.weight == 0.2
    assert score.info["verdict"] == "SATISFIED" and score.info["calls_used"] == 2
    assert score.info["tools_used"] == ["read_file", "diff_for_file"]
    assert score.info["files_read"] == ["src/app.py"] and score.info["statement"] == "run() returns 2"
    tool_reply = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert tool_reply["calls_remaining"] == 13
    assert llm.requests[0]["temperature"] == 0
    assert "+line 399" not in llm.requests[0]["messages"][1]["content"]  # never the raw big hunk


@pytest.mark.asyncio
async def test_judge_budget_forces_a_verdict_and_malformed_means_unmet(trees):
    row = uploads.RubricRow(id="r", requirement="x", weight=1.0)
    llm = FakeLLM(
        [[("list_dir", {"path": "."})], [("list_dir", {"path": "src"})], [("grep", {"pattern": "x"})], "no json here"]
    )
    score = await judge.judge_row(row, name="r", prompt="p", diff=DIFF, inspector=trees, client=llm, max_tool_calls=2)
    assert score.value == 0.0 and score.info["verdict"] == "UNSATISFIED"
    assert score.info["calls_used"] == 2
    last_tool_reply = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert last_tool_reply["calls_remaining"] == 0
    assert llm.requests[2]["tool_choice"] == "none"  # the third completion may not call tools
    assert score.info["reason"] == judge.MISSING_REASON


@pytest.mark.asyncio
async def test_negative_row_without_a_quote_does_not_fire(trees):
    row = uploads.RubricRow(id="n", requirement="Hides the race with a sleep", weight=0.1, negative=True)
    llm = FakeLLM(['{"verdict": "COMMITTED", "explanation": "surely it sleeps somewhere"}'])
    score = await judge.judge_row(row, name="n", prompt="p", diff=DIFF, inspector=trees, client=llm)
    assert score.weight == -0.1 and score.value == 0.0
    assert score.info["verdict"] == "NOT_COMMITTED" and score.info["reason"] == judge.NO_EVIDENCE_REASON
    assert "COMMITTED" in llm.requests[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_judge_outage_fails_closed(trees):
    class Down:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

    judge._RETRY_BACKOFF_S = 0.0
    row = uploads.RubricRow(id="r", requirement="x", weight=1.0, tools=False)
    score = await judge.judge_row(row, name="r", prompt="p", diff=DIFF, inspector=None, client=Down())
    assert score.value == 0.0 and "judge_error" in score.info


# ─── publishing: tasks.py packages and uploads at import ─────────────────


def test_zip_tree_is_deterministic_and_keeps_modes(tmp_path):
    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "HEAD").write_text("ref")
    (src / "run.sh").write_text("#!/bin/sh\n")
    (src / "run.sh").chmod(0o755)
    (src / "a.txt").write_text("a")
    one, two = uploads.zip_tree(src, tmp_path / "one.zip"), uploads.zip_tree(src, tmp_path / "two.zip")
    assert uploads.sha256(one) == uploads.sha256(two)
    with zipfile.ZipFile(one) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "run.sh"]
        assert (zf.getinfo("run.sh").external_attr >> 16) & 0o777 == 0o755
    out = tmp_path / "out"
    uploads.expand_zip(one, out)
    assert os.access(out / "run.sh", os.X_OK)


def _demo_task(tmp_path: Path, *, rubric: bool = True) -> Path:
    """A task folder whose codebase is a tiny local git repo (fetch works from a path)."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "answer.py").write_text("def answer():\n    return 41\n")
    for argv in (
        ["git", "init", "-q", "-b", "main", "."],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
    ):
        subprocess.run(argv, cwd=source, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True
    ).stdout.strip()
    folder = tmp_path / "tasks" / "demo"
    (folder / "grading").mkdir(parents=True)
    (folder / "prompt.md").write_text("Fix it.")
    (folder / "gold.diff").write_text("diff --git a/x b/x\n")
    (folder / "task.json").write_text(json.dumps({"slug": "demo", "codebase": {"repo_url": str(source), "sha": sha}}))
    (folder / "grading" / "run_grading.sh").write_text("#!/bin/sh\n")
    (folder / "grading" / "criteria.json").write_text("[]")
    if rubric:
        (folder / "llm_rubric.json").write_text("[]")
    return folder


def test_publish_uploads_once_then_serves_from_the_hash_cache(tmp_path, monkeypatch):
    folder = _demo_task(tmp_path)
    sent: list[str] = []
    monkeypatch.setattr(uploads, "upload_file", lambda path, **kw: (sent.append(path.name), f"id-{path.name}")[1])
    cache = tmp_path / "cache"
    ids, cached = uploads.publish(folder, cache_dir=cache, api_key="sk-test", api_url="https://api.example")
    assert not cached and sorted(sent) == ["codebase.zip", "gold.diff", "grading.zip", "llm_rubric.json"]
    assert ids == {
        "codebase": "id-codebase.zip",
        "grading": "id-grading.zip",
        "golden_solution": "id-gold.diff",
        "llm_rubric": "id-llm_rubric.json",
    }
    with zipfile.ZipFile(cache / "demo" / "codebase.zip") as zf:
        assert zf.namelist() == ["answer.py"]  # .git stripped

    # Second run: nothing changed, no upload, no key needed.
    monkeypatch.setattr(uploads, "upload_file", lambda *a, **kw: pytest.fail("uploaded despite cache hit"))
    again, cached = uploads.publish(folder, cache_dir=cache, api_key=None, api_url="https://api.example")
    assert cached and again == ids

    # One edited grader: exactly one upload, and a clear error when the key is missing.
    (folder / "grading" / "run_grading.sh").write_text("#!/bin/sh\necho changed\n")
    with pytest.raises(uploads.UploadError, match="demo: grading.zip needs uploading but HUD_API_KEY"):
        uploads.publish(folder, cache_dir=cache, api_key=None, api_url="https://api.example")
    sent.clear()
    monkeypatch.setattr(uploads, "upload_file", lambda path, **kw: (sent.append(path.name), "id-new")[1])
    changed, cached = uploads.publish(folder, cache_dir=cache, api_key="sk-test", api_url="https://api.example")
    assert (
        not cached
        and sent == ["grading.zip"]
        and changed["grading"] == "id-new"
        and changed["codebase"] == ids["codebase"]
    )


def test_publish_names_the_task_and_file_when_an_upload_fails(tmp_path, monkeypatch):
    folder = _demo_task(tmp_path, rubric=False)

    def boom(path, **kw):
        raise RuntimeError("503")

    monkeypatch.setattr(uploads, "upload_file", boom)
    with pytest.raises(uploads.UploadError, match="demo: uploading codebase.zip failed: 503"):
        uploads.publish(folder, cache_dir=tmp_path / "cache", api_key="sk-test", api_url="https://api.example")


def test_tasks_module_emits_one_row_per_folder_in_the_template_shape(tmp_path, monkeypatch, capsys):
    import importlib.util

    folder = _demo_task(tmp_path)
    monkeypatch.setenv("SWE_TASKS_DIR", str(folder.parent))
    monkeypatch.setattr(uploads, "upload_file", lambda path, **kw: f"id-{path.name}")
    monkeypatch.setattr("hud.settings.settings.api_key", "sk-test")
    spec = importlib.util.spec_from_file_location("tasks_under_test", Path(__file__).resolve().parents[1] / "tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (row,) = module.tasks
    assert row.env == "swe-task-example" and row.id == "swe-task" and row.slug == "demo"
    assert row.args == {
        "prompt": "Fix it.",
        "codebase": [{"file_id": "id-codebase.zip"}],
        "grading": [{"file_id": "id-grading.zip"}],
        "golden_solution": [{"file_id": "id-gold.diff"}],
        "llm_rubric": [{"file_id": "id-llm_rubric.json"}],
    }
    assert (
        capsys.readouterr().out.strip()
        == "demo: codebase=id-codebase.zip grading=id-grading.zip gold=id-gold.diff rubric=id-llm_rubric.json (uploaded)"
    )
