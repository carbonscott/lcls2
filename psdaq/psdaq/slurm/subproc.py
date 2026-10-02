"""Async helper for running subprocesses."""
import asyncio
import sys


class SubprocHelper:
    """Helper with a coroutine `run_exec` that runs a command with asyncio and returns its exit code."""
    async def run_exec(self, args, env=None, echo_output=True):
        """Start a subprocess without a shell."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await proc.communicate()
        if echo_output:
            if stdout:
                print(stdout.decode(), end="")
            if stderr:
                print(stderr.decode(), end="", file=sys.stderr)
        return proc.returncode
