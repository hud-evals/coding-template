"""Smoke tests for coding environment tools.

These tests run against a real Docker image via env.call_tool,
validating that tools respond correctly to known inputs.

Usage:
    uv run pytest tests/ -v
    uv run pytest tests/ -v --image my-image:latest
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# -- Bash tool --

async def test_bash_echo(env):
    """bash tool can run a simple echo command."""
    result = await env.call_tool("bash", command="echo hello")
    text = _get_text(result)
    assert "hello" in text


async def test_bash_pwd(env):
    """bash tool returns a working directory."""
    result = await env.call_tool("bash", command="pwd")
    text = _get_text(result)
    assert text.startswith("/")


async def test_bash_exit_code(env):
    """bash tool surfaces non-zero exit codes or errors."""
    result = await env.call_tool("bash", command="ls /nonexistent_path_xyz")
    text = _get_text(result)
    assert "no such file" in text.lower() or "cannot access" in text.lower() or "not found" in text.lower()


async def test_bash_multiline(env):
    """bash tool handles multi-line output."""
    result = await env.call_tool("bash", command="echo -e 'line1\\nline2\\nline3'")
    text = _get_text(result)
    assert "line1" in text
    assert "line3" in text


# -- Editor tool --

async def test_editor_view_file(env):
    """editor view reads an existing file."""
    result = await env.call_tool("editor", command="view", path="/etc/hostname")
    text = _get_text(result)
    assert not result.isError, f"editor view failed: {text}"
    assert len(text.strip()) > 0


async def test_editor_create_and_view(env):
    """editor can create a file and read it back."""
    test_path = "/tmp/test_editor_create.txt"
    content = "hello from test"

    create_result = await env.call_tool("editor", command="create", path=test_path, file_text=content)
    assert not create_result.isError, f"create failed: {_get_text(create_result)}"

    view_result = await env.call_tool("editor", command="view", path=test_path)
    text = _get_text(view_result)
    assert "hello from test" in text


async def test_editor_str_replace(env):
    """editor str_replace modifies file content."""
    test_path = "/tmp/test_editor_replace.txt"

    await env.call_tool("editor", command="create", path=test_path, file_text="foo bar baz")

    replace_result = await env.call_tool(
        "editor", command="str_replace", path=test_path, old_str="bar", new_str="REPLACED"
    )
    assert not replace_result.isError, f"str_replace failed: {_get_text(replace_result)}"

    # Verify via bash (independent of editor view)
    check = await env.call_tool("bash", command=f"cat {test_path}")
    assert "REPLACED" in _get_text(check)
    assert "bar" not in _get_text(check)


async def test_editor_view_nonexistent(env):
    """editor view on a nonexistent path returns an error."""
    result = await env.call_tool("editor", command="view", path="/nonexistent/file.txt")
    text = _get_text(result)
    assert "error" in text.lower() or result.isError


# -- Helpers --

def _get_text(result) -> str:
    """Extract text from an MCPToolResult."""
    parts = []
    for block in result.content or []:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)
