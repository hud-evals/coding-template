"""Shared fixtures for the coding-template test suite."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from hud import Environment

# Ensure the project root is on sys.path so imports like `from tools import ...` work.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--image",
        default=None,
        help="Docker image name or URL to test against (e.g. coding-template:dev or https://mcp.example.com)",
    )


@pytest.fixture(scope="session")
def image_name(request):
    """Resolve the target: --image flag > pyproject.toml [tool.hud].image."""
    name = request.config.getoption("--image")
    if name:
        return name

    # Fall back to pyproject.toml
    import tomllib

    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        name = data.get("tool", {}).get("hud", {}).get("image")
        if name:
            return name

    raise ValueError(
        "No target specified. Use --image <name-or-url> or set [tool.hud].image in pyproject.toml"
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def env(image_name):
    """A connected Environment. Supports both Docker image names and URLs."""
    env = Environment("coding")
    if image_name.startswith("http://") or image_name.startswith("https://"):
        env.connect_url(image_name)
    else:
        env.connect_image(image_name)
    async with env:
        yield env
