"""The slow one at ~78 ms, because it starts an interactive shell — which is
the only way to see aliases an rc file defines.

host.alias_command() decides what to run: `$SHELL -ic alias` on Linux and
macOS, PowerShell's `Get-Alias` on Windows, nothing when neither is there. Both
answer in `name=body` lines, so one parser covers all three.
"""

from pathlib import Path

from .. import host
from . import Kind, Result


def read(ctx):
    cmd = host.alias_command()
    if cmd is None:
        return Result.of(error="no shell here that reports aliases")
    out = host.run(cmd, timeout=ctx.timeout)
    if out is None:
        return Result.of(error=f"{Path(cmd[0]).name} did not report any aliases")
    table, bodies = {}, {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("alias "):
            line = line[6:]
        name, sep, body = line.partition("=")
        name = name.strip()
        if sep and name and " " not in name:
            table[name] = [name]
            bodies[name] = body.strip().strip("'\"")
    return Result.of(table, bodies)


KIND = Kind("shell-alias", read)
