"""Utility to run shell commands asynchronously with a timeout."""
import asyncio
import os

TRUNCATED_MESSAGE: str = "<response clipped><NOTE>To save on context only part of this file has been shown to you. You should retry this tool after you have searched inside the file with `grep -n` in order to find the line numbers of what you are looking for.</NOTE>"
MAX_RESPONSE_LEN: int = 16000


def maybe_truncate(content: str, truncate_after: int | None = MAX_RESPONSE_LEN):
    """Truncate content and append a notice if content exceeds the specified length."""
    return (
        content
        if not truncate_after or len(content) <= truncate_after
        else content[:truncate_after] + TRUNCATED_MESSAGE
    )


def demote():
    """Drop privileges to uid/gid 1000 for security.

    This function is intended to be used as a preexec_fn in subprocess calls
    to ensure commands run with reduced privileges.
    """
    os.setgid(1000)
    os.setuid(1000)


async def run(
    cmd: str,
    timeout: float | None = 120.0,
    truncate_after: int | None = MAX_RESPONSE_LEN,
    preexec_fn=demote,
):
    """Run a shell command asynchronously with a timeout.

    Args:
        cmd: Command to execute
        timeout: Command timeout in seconds
        truncate_after: Maximum response length before truncation
        preexec_fn: Function to run in child process before exec (default: demote).
                   Pass None to skip preexec, or any callable for custom behavior.

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=preexec_fn,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return (
            process.returncode or 0,
            maybe_truncate(stdout.decode(), truncate_after=truncate_after),
            maybe_truncate(stderr.decode(), truncate_after=truncate_after),
        )
    except TimeoutError as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError(
            f"Command '{cmd}' timed out after {timeout} seconds"
        ) from exc
