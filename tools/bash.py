import asyncio  # noqa -- swapping to trio would be beneficial, but not blocking atm
import os
import tempfile

from .base import CLIResult, ToolError, ToolResult


class _BashSession:
    """A session of a bash shell."""

    _started: bool
    _process: asyncio.subprocess.Process

    command: str = "/bin/bash"
    _output_delay: float = 0.2  # seconds
    _timeout: float = 120.0  # seconds (1 minute)
    _sentinel: str = "<<exit>>"

    def __init__(self):
        self._started = False
        self._timed_out = False

    async def start(self):
        if self._started:
            await asyncio.sleep(0)
            return

        def demote():
            # This only runs in the child process
            os.setsid()
            os.setgid(1000)
            os.setuid(1000)

        self._process = await asyncio.create_subprocess_shell(
            self.command,
            preexec_fn=demote,
            shell=True,
            bufsize=0,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._started = True

    def stop(self):
        """Terminate the bash shell."""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return
        self._process.terminate()

    async def run(self, command: str):
        """Execute a command in the bash shell."""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            await asyncio.sleep(0)
            return ToolResult(
                system="tool must be restarted",
                error=f"bash has exited with returncode {self._process.returncode}",
            )
        if self._timed_out:
            raise ToolError(
                f"timed out: bash has not returned in {self._timeout} seconds and must be restarted.",
            )

        # we know these are not None because we created the process with PIPEs
        assert self._process.stdin
        assert self._process.stdout
        assert self._process.stderr

        # send command to the process
        self._process.stdin.write(command.encode() + f"; echo '{self._sentinel}'\n".encode())
        await self._process.stdin.drain()

        # read output from the process, until the sentinel is found
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    await asyncio.sleep(self._output_delay)
                    # if we read directly from stdout/stderr, it will wait forever for
                    # EOF. use the StreamReader buffer directly instead.
                    output = self._process.stdout._buffer.decode()  # pyright: ignore[reportAttributeAccessIssue]
                    error = self._process.stderr._buffer.decode()  # pyright: ignore[reportAttributeAccessIssue]
                    if self._sentinel in output:
                        # strip the sentinel and break
                        output = output[: output.index(self._sentinel)]
                        break
        except TimeoutError:
            self._timed_out = True
            stdout_truncated = output[:10000] + "<response clipped>" if len(output) > 10000 else output
            stderr_truncated = error[:10000] + "<response clipped>" if len(error) > 10000 else error
            
            # Save full stdout and stderr to temporary files
            stdout_file = None
            stderr_file = None
            
            try:
                # Create temporary files for stdout and stderr
                with tempfile.NamedTemporaryFile(mode='w', prefix='bash_stdout_', suffix='.log', delete=False) as f:
                    f.write(output)
                    stdout_file = f.name
                
                with tempfile.NamedTemporaryFile(mode='w', prefix='bash_stderr_', suffix='.log', delete=False) as f:
                    f.write(error)
                    stderr_file = f.name
                
                raise ToolError(
                    f"timed out: bash has not returned in {self._timeout} seconds and must be restarted.\n"
                    f"Full logs saved to:\n"
                    f"  STDOUT: {stdout_file}\n"
                    f"  STDERR: {stderr_file}\n"
                    f"Truncated output:\n"
                    f"  STDOUT: {stdout_truncated}\n"
                    f"  STDERR: {stderr_truncated}",
                ) from None
            except Exception:
                # If file creation fails, fall back to original error message
                raise ToolError(
                    f"timed out: bash has not returned in {self._timeout} seconds and must be restarted. Full logs are saved to \n STDOUT: {stdout_truncated}\n STDERR: {stderr_truncated}",
                ) from None

        if output.endswith("\n"):
            output = output[:-1]

        if error.endswith("\n"):
            error = error[:-1]

        # clear the buffers so that the next output can be read correctly
        self._process.stdout._buffer.clear()  # pyright: ignore[reportAttributeAccessIssue]
        self._process.stderr._buffer.clear()  # pyright: ignore[reportAttributeAccessIssue]

        return CLIResult(output=output, error=error)


class BashTool:
    """
    A tool that allows the agent to run bash commands.
    The tool parameters are defined by Anthropic and are not editable.
    """

    _session: _BashSession | None

    def __init__(self):
        self._session = None

    async def __call__(self, command: str | None = None, restart: bool = False, **kwargs) -> ToolResult:
        if restart:
            if self._session:
                self._session.stop()
            self._session = _BashSession()
            await self._session.start()

            return ToolResult(system="tool has been restarted.")

        if self._session is None:
            self._session = _BashSession()
            await self._session.start()

        if command is not None:
            return await self._session.run(command)

        raise ToolError("no command provided.")