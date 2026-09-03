#!/usr/bin/env -S uv run --script
"""Upload a task folder's files as HUD data files and fill in its uploads.json.

    uv run tasks/upload.py <name>            # dry run: say what would be uploaded
    uv run tasks/upload.py <name> --run      # upload, write tasks/<name>/uploads.json

Optional: the console's data-file page does the same by hand. This uses the
route the console uses (``POST /v2/data`` for a presigned PUT url, the PUT,
then ``POST /v2/data/{id}/complete``); the route accepts a HUD API key
(``HUD_API_KEY``, sent as a bearer token). Files whose sha256 already sits in
``uploads.json`` are skipped, so re-running after editing one grader uploads
one file. Run ``tasks/pack.py`` first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from pack import sha256, task_folders, upload_paths

API = os.environ.get("HUD_API_URL", "https://api.hud.ai").rstrip("/")


def upload(client: httpx.Client, path: Path, key: str) -> str:
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "content_type": "application/octet-stream",
        "scope": "team",
    }
    created = client.post(f"{API}/v2/data", headers=headers, json=body)
    created.raise_for_status()
    file_id, url = created.json()["file"]["id"], created.json()["upload_url"]
    with path.open("rb") as handle:
        client.put(url, content=handle, headers={"Content-Type": "application/octet-stream"}).raise_for_status()
    client.post(f"{API}/v2/data/{file_id}/complete", headers=headers).raise_for_status()
    return file_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks", nargs="*", help="task folder names (default: all)")
    parser.add_argument("--run", action="store_true", help="actually upload (default is a dry run)")
    options = parser.parse_args()
    key = os.environ.get("HUD_API_KEY", "")
    if options.run and not key:
        sys.exit("HUD_API_KEY is not set")
    with httpx.Client(timeout=httpx.Timeout(60.0, write=1800.0)) as client:
        for folder in task_folders(options.tasks):
            record_path = folder / "uploads.json"
            record = json.loads(record_path.read_text()) if record_path.is_file() else {}
            print(f"{folder.name}:")
            for arg, path in upload_paths(folder).items():
                if not path.is_file():
                    sys.exit(f"{folder.name}: {path.name} missing; run tasks/pack.py first")
                digest = sha256(path)
                entry = record.get(arg)
                if isinstance(entry, dict) and entry.get("sha256") == digest and entry.get("file_id"):
                    print(f"  {arg:16} unchanged -> {entry['file_id']}")
                    continue
                if not options.run:
                    print(f"  {arg:16} WOULD upload {path.name} ({path.stat().st_size:,} bytes, sha256 {digest[:12]})")
                    continue
                file_id = upload(client, path, key)
                record[arg] = {"file_id": file_id, "sha256": digest}
                record_path.write_text(json.dumps(record, indent=2) + "\n")
                print(f"  {arg:16} uploaded {path.name} -> {file_id}")
    if not options.run:
        print("\ndry run; add --run to upload")


if __name__ == "__main__":
    main()
