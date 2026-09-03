"""The task rows for ``hud sync tasks <taskset> tasks.py --yes`` and ``hud eval tasks.py``.

One ``Task`` per ``tasks/<name>/`` folder, on the ``swe-task`` template of the
one deployed environment. The row is the prompt plus the ids of the four
uploads; the ids come from ``tasks/<name>/uploads.json``, which the operator
fills after uploading (console, or ``tasks/upload.py``)::

    {"codebase": "<file_id>", "grading": "<file_id>",
     "golden_solution": "<file_id>", "llm_rubric": "<file_id>"}

(``tasks/upload.py`` writes ``{"file_id": ..., "sha256": ...}`` per key; both
shapes are read.) A folder whose ids are still placeholders is reported and
left out, so a half-filled tree never syncs a broken row.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from hud.eval.task import Task

ENV_NAME = "swe-task-example"  # Environment(name=...) in env.py
TEMPLATE_ID = "swe-task"  # @env.template(id=...) in env.py
TASKS_DIR = Path(__file__).resolve().parent / "tasks"
UPLOADS = ("codebase", "grading", "golden_solution", "llm_rubric")


def _file_id(record: dict, key: str, folder: Path) -> str | None:
    value = record.get(key)
    if isinstance(value, dict):
        value = value.get("file_id")
    if not value or not isinstance(value, str) or value.startswith("<"):
        return None
    return value


def task_for(folder: Path) -> Task | None:
    meta = json.loads((folder / "task.json").read_text("utf-8"))
    uploads = folder / "uploads.json"
    if not uploads.is_file():
        print(
            f"tasks.py: {folder.name} skipped: no uploads.json (run tasks/pack.py, upload, fill the ids)",
            file=sys.stderr,
        )
        return None
    record = json.loads(uploads.read_text("utf-8"))
    ids = {key: _file_id(record, key, folder) for key in UPLOADS}
    needed = ["codebase", "grading", "golden_solution"] + (
        ["llm_rubric"] if (folder / "llm_rubric.json").is_file() else []
    )
    missing = [key for key in needed if ids[key] is None]
    if missing:
        print(f"tasks.py: {folder.name} skipped: uploads.json has no file id for {', '.join(missing)}", file=sys.stderr)
        return None
    args = {"prompt": (folder / "prompt.md").read_text("utf-8")}
    for key in needed:
        args[key] = [{"file_id": ids[key]}]
    return Task(
        env=ENV_NAME,
        id=TEMPLATE_ID,
        slug=meta.get("slug", folder.name),
        args=args,
        columns={"repo": meta["codebase"]["repo_url"], "description": meta.get("description", "")},
    )


tasks: list[Task] = [
    task
    for folder in sorted(p for p in TASKS_DIR.iterdir() if (p / "task.json").is_file())
    if (task := task_for(folder)) is not None
]

if __name__ == "__main__":
    for task in tasks:
        print(task.slug, json.dumps({k: v for k, v in task.args.items() if k != "prompt"}))
