"""`vim -es -c map` reports what vim actually has; grepping .vimrc found 0 of
13, because a grep does not know that `nnoremap` is a map."""

import os
import tempfile
from pathlib import Path

from .. import host
from . import Kind, Result


def read(ctx):
    base = ["vim", "-N", "-u", str(ctx.conf) if ctx.conf else "NONE", "-es"]
    out = capture(base, ctx.timeout)
    if out is None:
        return Result.of(error="vim not installed, or refused -es")
    return Result.of(parse(out))


def capture(base, timeout=5):
    """The `redir` is not optional: in silent ex mode `:map` writes to the
    message area, not to stdout, so without it the pipe is empty and the probe
    looks like a vim that has no mappings at all.

    Windows has no /dev/stdout, so there it redirects to a temp file and reads
    it back — same command, one more hop.
    """
    sink = host.vim_redirect()
    if sink:
        return host.run(
            base + ["-c", f"redir >> {sink}", "-c", "map", "-c", "qa!"],
            stdin=host.devnull_stdin(),
            timeout=timeout,
        )
    handle, raw = tempfile.mkstemp(prefix="howto-vim-map-", suffix=".txt")
    os.close(handle)
    tmp = Path(raw)
    host.run(base + ["-c", f"redir! > {tmp}", "-c", "map", "-c", "redir END", "-c", "qa!"],
             stdin=host.devnull_stdin(), timeout=timeout)
    try:
        return tmp.read_text(encoding="utf-8", errors="replace") or None
    except OSError:
        return None
    finally:
        tmp.unlink(missing_ok=True)


def parse(out):
    table = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3 or len(parts[0]) > 3:
            continue
        lhs, rhs = parts[1], parts[2]
        if lhs.startswith("<Plug>") or rhs.startswith("<Plug>"):
            continue  # an internal hop, not something you press
        rhs = rhs.lstrip("*&@ ").strip()  # the remappability flags
        if rhs:
            table.setdefault(rhs, []).append(lhs)
    return table


KIND = Kind("vim-map", read)
