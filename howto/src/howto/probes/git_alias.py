"""Grepping [alias] in ~/.gitconfig found 0 of 5 — the names are bare."""

from .. import host
from . import Kind, Result


def read(ctx):
    out = host.run(["git", "config", "--get-regexp", r"^alias\."], timeout=ctx.timeout)
    if out is None:
        return Result.of(error="git not installed, or no aliases set")
    table, bodies = {}, {}
    for line in out.splitlines():
        name, _, body = line.partition(" ")
        if not name.startswith("alias."):
            continue
        alias = name[len("alias.") :]
        table[alias] = [f"git {alias}"]
        bodies[alias] = body.strip()
    return Result.of(table, bodies)


KIND = Kind("git-alias", read)
