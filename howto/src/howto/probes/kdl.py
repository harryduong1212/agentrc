"""zellij's `config.kdl`. If zellij or its config is absent, this degrades
loudly instead of reporting an empty table.

There is no kdl parser in the stdlib and adding a dependency for one file is a
bad trade, so this reads the single-line form `bind "x" { Action; }`. That
covers the shape zellij's own default config is written in, and a multi-line
block simply does not match — which is visible as a missing row, not as a wrong
key.
"""

import shlex

from . import Kind, Result


def read(ctx):
    if not ctx.conf or not ctx.conf.is_file():
        return Result.of(error=f"no config at {ctx.conf}")
    try:
        text = ctx.conf.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return Result.of(error=f"{ctx.conf.name}: {exc}")
    return Result.of(parse(text))


def parse(text):
    table = {}
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("bind ") or "{" not in s:
            continue
        try:
            keys = shlex.split(s[5:].split("{")[0])
        except ValueError:  # an unbalanced quote is a line we skip, not a crash
            continue
        tail = s.split("{", 1)[1].strip().split()
        action = tail[0].strip(";}") if tail else ""
        if action and keys:
            table.setdefault(action, []).extend(keys)
    return table


KIND = Kind("kdl", read)
