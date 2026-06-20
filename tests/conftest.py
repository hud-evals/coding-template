"""Shared fixtures for the coding environment test suite (HUD v6).

v6 drives a *served* environment through a placement provider (a ``runtime``)
plus the ``connect`` + ``Run`` client lifecycle — there is no in-process
``Environment`` client (``connect_image`` / ``call_tool`` / ``read_resource``
are gone). The ``runtime`` fixture resolves a provider from:

    --url tcp://host:port   -> Runtime(url)        (attach to an env served elsewhere)
    --image name-or-url     -> DockerRuntime(name) (fresh container per rollout)
    else                    -> [tool.hud].image from pyproject.toml
"""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `from env import ...` / `from tasks
# import ...` resolve when running pytest from the repo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--image",
        default=None,
        help="Docker image name to serve the env from (e.g. coding-template:dev)",
    )
    parser.addoption(
        "--url",
        default=None,
        help="tcp:// url of an already-served env control channel (e.g. tcp://127.0.0.1:8765)",
    )


@pytest.fixture(scope="session")
def runtime(request):
    """A v6 placement provider for the environment under test.

    Resolution order: --url (attach) > --image (fresh container per rollout) >
    default LocalRuntime (serve from source; clones the substrate per rollout —
    no Docker, works on macOS/Linux).
    """
    from hud import DockerRuntime, LocalRuntime, Runtime

    url = request.config.getoption("--url")
    if url:
        return Runtime(url)

    image = request.config.getoption("--image")
    if image:
        return DockerRuntime(image)

    return LocalRuntime(str(PROJECT_ROOT / "tasks.py"))
