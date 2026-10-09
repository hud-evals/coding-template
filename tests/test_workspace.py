"""The uid-walled workspace must run agent commands on every supported hud SDK."""

import shutil

import asyncssh
import pytest

from env import UidWallWorkspace


@pytest.mark.skipif(
    shutil.which("bwrap") is not None,
    reason="with bwrap the SDK launches sessions without shell_argv; the image has no bwrap",
)
@pytest.mark.asyncio
async def test_agent_shell_runs_a_command(tmp_path):
    ws = UidWallWorkspace(tmp_path / "repo")
    await ws.start()
    try:
        host, port = ws.ssh_url.removeprefix("ssh://").split(":")
        async with asyncssh.connect(
            host,
            int(port),
            username=ws.ssh_user,
            client_keys=[str(ws.ssh_client_key_path)],
            known_hosts=None,
        ) as conn:
            result = await conn.run("echo ok")
    finally:
        await ws.stop()

    assert (result.exit_status, result.stdout, result.stderr) == (0, "ok\n", "")
