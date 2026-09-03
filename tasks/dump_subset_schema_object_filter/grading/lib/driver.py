"""Build the candidate tree's dump driver and run it.

The driver (grader/gohar) is a module of its own that reaches the tree under
test through a replace directive written here. Nothing from the workspace is
imported, executed or trusted beyond the exported API it compiles against.
"""

import hashlib
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
GRADER_DIR = os.environ.get("GRADER_DIR") or os.path.dirname(HERE)
STATE_DIR = os.environ.get("GRADER_STATE_DIR") or os.path.join(GRADER_DIR, ".calib", "state")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")

FIXTURES_DIR = os.path.join(GRADER_DIR, "data", "fixtures")


class DriverError(RuntimeError):
    pass


def go_env(state):
    env = dict(os.environ)
    env.update({
        # workspace mode refuses -mod=mod; the module graph comes from the
        # workspace, so readonly is what we want anyway
        "GOFLAGS": "",
        "GOPROXY": env.get("GRADER_GOPROXY", "off"),
        "GOTOOLCHAIN": "local",
        "GOWORK": os.path.join(state, "go.work"),
        "CGO_ENABLED": "1",
        "GOCACHE": env.get("GOCACHE") or os.path.join(state, "gocache"),
    })
    env.setdefault("HOME", "/root")
    return env


def build(repo=None, state=None):
    """Compile gohar against the tree under test. Returns the binary path."""
    repo = os.path.abspath(repo or REPO_DIR)
    state = os.path.abspath(state or STATE_DIR)
    src = os.path.join(state, "gohar")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(os.path.join(GRADER_DIR, "gohar"), src)

    mod = open(os.path.join(src, "go.mod")).read().replace("__REPO_DIR__", repo)
    open(os.path.join(src, "go.mod"), "w").write(mod)

    with open(os.path.join(state, "go.work"), "w") as fh:
        fh.write("go 1.26.0\n\nuse (\n\t%s\n\t%s\n)\n" % (repo, src))

    binary = os.path.join(state, "bin", "gohar")
    os.makedirs(os.path.dirname(binary), exist_ok=True)
    if os.path.exists(binary):
        os.remove(binary)
    proc = subprocess.run(
        ["go", "build", "-o", binary, "."],
        cwd=src, env=go_env(state), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=1500,
    )
    if proc.returncode != 0 or not os.path.exists(binary):
        raise DriverError(
            "the dump driver does not compile against this tree -- either it does "
            "not build at all, or the exported shape of the dump API moved:\n"
            + proc.stdout.decode("utf-8", "replace")[-4000:]
        )
    return binary


def tree_digest(repo):
    """A content digest over everything the driver could compile. The criteria
    run one after another against a tree that does not move, so the dumps are
    computed once; the moment a byte of Go source differs, the key differs and
    they are computed again."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "testdata", "node_modules"))
        for name in sorted(files):
            if not (name.endswith(".go") or name in ("go.mod", "go.sum")):
                continue
            path = os.path.join(root, name)
            h.update(os.path.relpath(path, repo).encode())
            try:
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 18), b""):
                        h.update(chunk)
            except OSError:
                h.update(b"<unreadable>")
    return h.hexdigest()[:32]


def run_jobs(jobs, repo=None, state=None, fixtures=None, label="jobs"):
    """Produce a dump for every job. Returns {job id: result dict}."""
    repo_dir = os.path.abspath(repo or REPO_DIR)
    state = os.path.abspath(state or STATE_DIR)
    os.makedirs(state, exist_ok=True)

    key = hashlib.sha256(
        (tree_digest(repo_dir) + json.dumps(jobs, sort_keys=True)).encode()
    ).hexdigest()[:32]
    out_dir = os.path.join(state, "dumps", label, key)
    cached = os.path.join(out_dir, "results.json")
    if os.path.exists(cached):
        with open(cached) as fh:
            return {r["id"]: r for r in json.load(fh)}

    binary = build(repo=repo_dir, state=state)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)

    spec = {
        "fixtures_dir": os.path.abspath(fixtures or FIXTURES_DIR),
        "out_dir": out_dir,
        "jobs": jobs,
    }
    spec_path = os.path.join(out_dir, "spec.json")
    with open(spec_path, "w") as fh:
        json.dump(spec, fh)

    proc = subprocess.run(
        [binary, spec_path], cwd=state, env=go_env(state),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900,
    )
    if proc.returncode != 0:
        raise DriverError(
            "the dump driver failed to run:\n"
            + proc.stderr.decode("utf-8", "replace")[-4000:]
        )
    results = json.loads(proc.stdout.decode("utf-8", "replace"))
    with open(cached, "w") as fh:
        json.dump(results, fh)
    return {r["id"]: r for r in results}
