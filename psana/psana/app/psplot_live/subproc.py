"""Helper that starts shell commands as asyncio subprocesses and records them by process id."""
import asyncio


class SubprocHelper:
    """Start shell commands as asyncio subprocesses and keep them in `procs`, keyed by pid.

    The coroutine `_run(cmd, callback)` (whose docstring says it starts psplot) uses
    `asyncio.create_subprocess_shell` with piped stdout and stderr and calls `callback(pid)` if
    given.
    """
    def __init__(self):
        self.procs = {}

    async def _run(self, cmd, callback=None):
        """Start psplot as a subprocess"""
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        self.procs[proc.pid] = proc
        if callback:
            callback(proc.pid)

    def pids(self):
        """Return the list of process ids of the started subprocesses."""
        return list(self.procs.keys())
