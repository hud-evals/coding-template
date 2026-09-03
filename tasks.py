"""The task rows: ``hud sync tasks <taskset> tasks.py --yes`` publishes every task folder.

One ``Task`` per ``tasks/<name>/`` on the ``swe-task`` template of the one
deployed environment. Importing this module packages each folder (the
codebase at its sha, the grading pack) and uploads whatever changed as HUD
data files, keyed by content hash in the gitignored ``tasks/.cache/``; an
unchanged folder makes no network call. ``HUD_API_KEY`` (the key ``hud
deploy`` uses) is needed only when something must be uploaded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from hud.eval.task import Task
from hud.settings import settings

from coding.uploads import publish

ENV_NAME = "swe-task-example"  # Environment(name=...) in env.py
TEMPLATE_ID = "swe-task"  # @env.template(id=...) in env.py
TASKS_DIR = Path(os.environ.get("SWE_TASKS_DIR") or Path(__file__).resolve().parent / "tasks")
CACHE_DIR = TASKS_DIR / ".cache"


def task_for(folder: Path) -> Task:
    meta = json.loads((folder / "task.json").read_text("utf-8"))
    ids, cached = publish(
        folder, cache_dir=CACHE_DIR, api_key=settings.api_key, api_url=settings.hud_api_url.rstrip("/")
    )
    slug = meta.get("slug", folder.name)
    shown = " ".join(
        f"{k}={v}"
        for k, v in (
            ("codebase", ids["codebase"]),
            ("grading", ids["grading"]),
            ("gold", ids["golden_solution"]),
            ("rubric", ids.get("llm_rubric")),
        )
        if v
    )
    print(f"{slug}: {shown} ({'cached' if cached else 'uploaded'})")
    return Task(
        env=ENV_NAME,
        id=TEMPLATE_ID,
        slug=slug,
        args={
            "prompt": (folder / "prompt.md").read_text("utf-8"),
            **{arg: [{"file_id": file_id}] for arg, file_id in ids.items()},
        },
        columns={"repo": meta["codebase"]["repo_url"], "description": meta.get("description", "")},
    )


tasks: list[Task] = [
    task_for(folder) for folder in sorted(p for p in TASKS_DIR.iterdir() if (p / "task.json").is_file())
]
