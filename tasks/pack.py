#!/usr/bin/env -S uv run --script
"""Build the two zips a task folder uploads. Local only; nothing talks to HUD.

    uv run tasks/pack.py                     # every folder under tasks/
    uv run tasks/pack.py exemplar_storage_contention

For ``tasks/<name>/`` this writes, into the gitignored ``tasks/<name>/dist/``:

- ``codebase.zip`` - the repository named in ``task.json`` at its sha, fetched
  once into a cache under ``/tmp``, zipped without ``.git``.
- ``grading.zip`` - the ``grading/`` folder as is: ``run_grading.sh``,
  ``criteria.json``, hidden tests, optional ``setup.sh`` / ``services.sh``.

``gold.diff`` and ``llm_rubric.json`` are uploaded straight from the folder.
Zips are deterministic (fixed timestamps), so an unchanged folder zips to the
same bytes and ``upload.py`` can tell it has nothing new to send.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent
CODEBASE_CACHE = Path(tempfile.gettempdir()) / "swe-task-codebases"
UPLOADED_FILES = ("codebase.zip", "grading.zip", "gold.diff", "llm_rubric.json")
_ZIP_TIME = (2000, 1, 1, 0, 0, 0)


def task_folders(names: list[str]) -> list[Path]:
    folders = (
        [TASKS_DIR / n for n in names]
        if names
        else sorted(p for p in TASKS_DIR.iterdir() if (p / "task.json").is_file())
    )
    for folder in folders:
        for required in ("task.json", "prompt.md", "gold.diff", "grading/run_grading.sh", "grading/criteria.json"):
            if not (folder / required).is_file():
                sys.exit(f"{folder.name}: {required} is missing")
    return folders


def fetch_codebase(repo_url: str, sha: str) -> Path:
    """The repo at ``sha`` in the cache (a shallow fetch of that one commit)."""
    dest = CODEBASE_CACHE / sha
    if (dest / ".git").is_dir():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["git", "init", "-q", str(dest)],
        ["git", "-C", str(dest), "remote", "add", "origin", repo_url],
        ["git", "-C", str(dest), "fetch", "-q", "--depth", "1", "origin", sha],
        ["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"],
    ):
        subprocess.run(argv, check=True)
    return dest


def zip_tree(source: Path, out: Path, *, skip: tuple[str, ...] = (".git", "__pycache__")) -> Path:
    """A deterministic zip of ``source`` keeping file modes and in-tree symlinks."""
    entries = sorted(p for p in source.rglob("*") if not any(part in skip for part in p.relative_to(source).parts))
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in entries:
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=_ZIP_TIME)
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, os.readlink(path))
            elif stat.S_ISREG(mode):
                info.external_attr = (stat.S_IFREG | (mode & 0o7777)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, path.read_bytes())
    return out


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_paths(folder: Path) -> dict[str, Path]:
    """Argument name -> the file to upload for it (llm_rubric only when the folder has one)."""
    paths = {
        "codebase": folder / "dist" / "codebase.zip",
        "grading": folder / "dist" / "grading.zip",
        "golden_solution": folder / "gold.diff",
    }
    if (folder / "llm_rubric.json").is_file():
        paths["llm_rubric"] = folder / "llm_rubric.json"
    return paths


def pack(folder: Path) -> dict[str, Path]:
    meta = json.loads((folder / "task.json").read_text())
    codebase = meta["codebase"]
    dist = folder / "dist"
    zip_tree(fetch_codebase(codebase["repo_url"], codebase["sha"]), dist / "codebase.zip")
    zip_tree(folder / "grading", dist / "grading.zip")
    paths = upload_paths(folder)
    print(f"{folder.name}:")
    for arg, path in paths.items():
        print(
            f"  {arg:16} {path.relative_to(TASKS_DIR.parent)}  {path.stat().st_size:,} bytes  sha256 {sha256(path)[:12]}"
        )
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks", nargs="*", help="task folder names (default: all)")
    options = parser.parse_args()
    for folder in task_folders(options.tasks):
        pack(folder)
    print(
        "\nnext: upload the files above (console, or `uv run tasks/upload.py <name> --run`), then fill tasks/<name>/uploads.json"
    )


if __name__ == "__main__":
    main()
