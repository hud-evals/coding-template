"""What a ``swe-task`` receives: uploaded files and the two grading tables.

Every ``swe-task`` argument except the prompt is a data file uploaded to the
platform and referenced by id. This module downloads and stages them (zips
unpack in place) and validates the two tables a contributor writes:
``criteria.json`` inside the grading zip, one row per ``run_grading.sh``
function, and the optional ``llm_rubric.json``, one row per LLM-judged
criterion. Same row shape in both, so a contributor learns one format.
"""

from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from hud.settings import settings
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

CRITERIA_FILE = "criteria.json"
_ID = r"^[A-Za-z0-9_-]+$"


class DataFileRef(BaseModel):
    """One uploaded file; the console's data-file picker hands this over."""

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(description="Id of the uploaded data file.")
    path: str | None = Field(
        default=None, description="Destination name under the staging root; default: the uploaded name."
    )


class CriterionRow(BaseModel):
    """One row of ``criteria.json``: one deterministic grader, one subscore.

    ``bash run_grading.sh <id>`` runs in the repo; exit 0 passes; a last
    ``GRADER_SCORE <0..1>`` line on stdout makes the value fractional. A
    ``gate`` carries no weight: failing it caps the reward instead. A
    ``blocker`` scales the reward down when it fails. ``pristine_paths`` are
    checked out from the baseline before the row runs (an edited assertion
    cannot buy a pass) and the agent's tree is put back afterwards.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    statement: str = Field(min_length=1, validation_alias=AliasChoices("requirement", "statement"))
    id: str | None = Field(default=None, pattern=_ID)
    weight: float = Field(default=1.0, ge=0.0)
    blocker: bool = False
    gate: bool = False
    timeout: int = Field(default=900, gt=0)
    pristine_paths: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _gate_has_no_weight(self) -> CriterionRow:
        if self.gate:
            object.__setattr__(self, "weight", 0.0)
        return self


class RubricRow(BaseModel):
    """One row of ``llm_rubric.json``: one LLM-judged criterion, one subscore.

    Judged on its own against the agent's change, so facts never carry
    between rows. ``negative`` rows describe a mistake: the judge must quote
    the code that commits it, and the row's weight is applied as a penalty.
    ``tools=false`` falls back to a cheap diff-only judge call.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    statement: str = Field(min_length=1, validation_alias=AliasChoices("requirement", "statement"))
    id: str | None = Field(default=None, pattern=_ID)
    weight: float = Field(default=1.0, gt=0.0)
    guidance: str | None = None
    negative: bool = False
    partial: bool = False
    tools: bool = True
    model: str | None = None


def criterion_id(row: CriterionRow | RubricRow, index: int) -> str:
    """Subscore name and (for criteria) the bash function name."""
    if row.id:
        return row.id
    slug = "".join(ch if ch.isalnum() else "_" for ch in row.statement.lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or f"c{index}"


def _rows(data: Any, adapter: TypeAdapter, what: str) -> list:
    if isinstance(data, dict) and "criteria" in data:
        data = data["criteria"]
    rows = adapter.validate_python(data)
    if not rows:
        raise ValueError(f"{what} has no rows")
    names = [criterion_id(row, index) for index, row in enumerate(rows, start=1)]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"{what}: duplicate ids {duplicates}")
    return rows


def parse_criteria(data: Any) -> list[CriterionRow]:
    rows = _rows(data, TypeAdapter(list[CriterionRow]), CRITERIA_FILE)
    if not any(row.weight > 0 for row in rows):
        raise ValueError(f"{CRITERIA_FILE}: no row carries weight")
    return rows


def parse_rubric(data: Any) -> list[RubricRow]:
    return _rows(data, TypeAdapter(list[RubricRow]), "llm_rubric.json")


def load_criteria(grader_dir: Path) -> list[CriterionRow]:
    path = grader_dir / CRITERIA_FILE
    if not path.is_file():
        raise ValueError(f"{CRITERIA_FILE} missing from the grading zip")
    return parse_criteria(json.loads(path.read_text("utf-8")))


def load_rubric(path: Path) -> list[RubricRow]:
    return parse_rubric(json.loads(path.read_text("utf-8")))


# ─── download and stage ──────────────────────────────────────────────────

_TIMEOUT = httpx.Timeout(30.0, read=600.0)


class DataFileError(RuntimeError):
    """A referenced data file could not be read or staged."""


def destination(root: Path, relative: str) -> Path:
    """Resolve a root-relative path, refusing anything that escapes it."""
    candidate = PurePosixPath(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts or "\\" in relative:
        raise DataFileError(f"unsafe data file path: {relative!r}")
    return root / candidate


def expand_zip(archive: Path, root: Path) -> list[Path]:
    """Unpack into ``root`` and delete the archive.

    Modes come back with the files (a repo's scripts need their exec bits and
    ``zipfile`` drops them); symlinks are recreated only when they stay inside
    ``root``. A single top-level wrapper folder (GitHub-style zips) is stripped.
    """
    written: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        for name in names:
            posix = PurePosixPath(name)
            if posix.is_absolute() or ".." in posix.parts:
                raise DataFileError(f"unsafe zip member: {name!r}")
        tops = {PurePosixPath(n).parts[0] for n in names}
        prefix = tops.pop() if len(tops) == 1 and all(len(PurePosixPath(n).parts) > 1 for n in names) else ""
        for info in infos:
            rel = str(PurePosixPath(info.filename).relative_to(prefix)) if prefix else info.filename
            dest = destination(root, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            mode = (info.external_attr >> 16) & 0o7777
            if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                target = zf.read(info.filename).decode("utf-8", "replace")
                if not (dest.parent / target).resolve().is_relative_to(root.resolve()):
                    raise DataFileError(f"symlink escapes the staging root: {info.filename!r} -> {target!r}")
                if dest.is_symlink() or dest.exists():
                    dest.unlink()
                os.symlink(target, dest)
            else:
                dest.write_bytes(zf.read(info.filename))
                if mode:
                    dest.chmod(mode)
            written.append(dest)
    archive.unlink(missing_ok=True)
    return written


def _api(api_key: str | None) -> tuple[str, dict[str, str]]:
    key = (api_key or settings.api_key or "").strip()
    if not key:
        raise DataFileError("HUD_API_KEY is unset; the environment cannot read data files")
    return settings.hud_api_url.rstrip("/"), {"Authorization": f"Bearer {key}"}


async def _get(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get(url, headers=headers)
    if response.is_error:
        raise DataFileError(f"GET {url} failed: {response.status_code}")
    return response.json()


async def stage(ref: DataFileRef, root: Path, *, api_key: str | None = None, unpack: bool = True) -> Path:
    """Download one upload under ``root``; a zip expands in place when ``unpack``.

    Returns the file written (or ``root`` after unpacking a zip).
    """
    base, headers = _api(api_key)
    root.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        meta = await _get(client, f"{base}/v2/data/{ref.file_id}", headers)
        filename = meta.get("filename") or ""
        link = await _get(client, f"{base}/v2/data/{ref.file_id}/download", headers)
        url = link.get("url") or link.get("download_url") or ""
        if not filename or not url:
            raise DataFileError(f"data file {ref.file_id} has no filename or download url")
        dest = destination(root, ref.path or filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with client.stream("GET", url) as response:
            if response.is_error:
                raise DataFileError(f"downloading data file {ref.file_id} failed: {response.status_code}")
            with dest.open("wb") as out:
                async for chunk in response.aiter_bytes(1 << 20):
                    out.write(chunk)
    if unpack and (dest.suffix.lower() == ".zip" or filename.lower().endswith(".zip")):
        expand_zip(dest, root)
        return root
    return dest
