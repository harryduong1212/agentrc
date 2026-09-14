"""Probes: an action token -> the key(s) that currently invoke it, here, now.

A functional core with one small imperative shell. Each probe module exports a
plain `read(ctx) -> Result` — give it a config path, get a table back, no self,
no inheritance, testable with a string. The only mutable thing in the package
is `Session`, thirty lines that memoise those reads.

That split is the point: the old design had a nine-deep class hierarchy where
every probe inherited a cache it did not write and a resolve it usually did not
want. Two of them overrode `resolve`, two carried `bodies`, one had `children`.
Those are three optional capabilities, so they are three optional fields on a
record rather than three branches of a base class.
"""

import time
from typing import Callable, NamedTuple, Optional

from ..doc import mtime

class Ctx(NamedTuple):
    """Everything a probe is allowed to know: where its config is, the header of
    the file that asked, and how long it may take. No back-reference to the app.

    The timeout rides here rather than in a module global so that config.toml
    reaches the probes by being passed, not by being stashed.
    """

    conf: object
    meta: dict
    timeout: int = 5

    @classmethod
    def of(cls, doc, timeout=5):
        return cls(doc.conf, doc.meta, timeout)


class Result(NamedTuple):
    table: tuple = ()  # (action, keys) pairs
    bodies: tuple = ()  # (action, body) pairs
    error: str = ""

    @classmethod
    def of(cls, table=None, bodies=None, error=""):
        return cls(tuple((key, tuple(value)) for key, value in (table or {}).items()),
                   tuple((key, value) for key, value in (bodies or {}).items()), error)


class Kind(NamedTuple):
    """One probe. `resolve` and `children` are optional because most probes
    want neither."""

    name: str
    read: Callable
    resolve: Optional[Callable] = None  # (table, token, width) -> str | None
    children: Optional[Callable] = None  # (ctx, token) -> [(token, desc, depth)]


# ============================================================ shared helpers


def add(table, key, value):
    """Append without repeating — several keys may reach one action, but the
    same key reaching it twice is the probe seeing one binding in two tables."""
    seen = table.setdefault(key, [])
    if value not in seen:
        seen.append(value)


def join_keys(keys, width):
    """As many as fit, then `+N`. tmux binds select-pane to twelve keys; a row
    that lists all twelve is not a cheatsheet, and one that silently truncates
    at the column edge is worse — it looks like a key you could press."""
    out = []
    for k in keys:
        nxt = ", ".join(out + [k])
        if out and len(nxt) > width - 4:
            return f"{', '.join(out)} +{len(keys) - len(out)}"
        out.append(k)
    return ", ".join(out)


def lookup(table, token, width):
    """The default resolve: exact hit, joined."""
    v = table.get(token)
    if not v:
        return None
    return join_keys(v, width) if isinstance(v, (list, tuple)) else str(v)


def degraded(name):
    """A kind we describe but cannot read on this machine. It says so once at
    the panel top; the literal rows still render, rather than the pane going
    blank."""

    def read(ctx):
        return Result.of(error=f"{name}: not readable on this machine")

    return Kind(name, read)


# =================================================================== registry


def registry():
    # Imported here, not at module scope, so one broken probe module cannot
    # stop howto from starting — it degrades to "not readable" instead.
    from . import git_alias, helpcmd, kdl, shell_alias, tmux, toml_actions, vim_map, yaml_keys

    return {
        k.name: k
        for k in (
            tmux.KIND,
            toml_actions.KIND,
            git_alias.KIND,
            vim_map.KIND,
            shell_alias.KIND,
            helpcmd.KIND,
            yaml_keys.KIND,
            kdl.KIND,
        )
    }


_REGISTRY = None


def kind_for(name):
    global _REGISTRY
    if _REGISTRY is None:
        try:
            _REGISTRY = registry()
        except Exception:  # a probe module that will not import must not be fatal
            _REGISTRY = {}
    return _REGISTRY.get(name) or (degraded(name) if name else None)


# ============================================================== the one shell


class Reading(NamedTuple):
    """A memoised read, with the three optional capabilities bound to it."""

    kind: Kind
    ctx: Ctx
    result: Result
    probed_at: float

    @property
    def table(self):
        return dict(self.result.table)

    @property
    def error(self):
        return self.result.error

    def resolve(self, token, width):
        """The keys bound to this action, or None when nothing is."""
        if self.kind.resolve:
            return self.kind.resolve(self.table, token, width)
        return lookup(self.table, token, width)

    def children(self, token):
        return self.kind.children(self.ctx, token) if self.kind.children else []

    def body(self, token):
        return dict(self.result.bodies).get(token, "")


class Session:
    """Memoises reads for as long as howto is open.

    The cache stats its source before reuse, so editing ~/.tmux.conf in another
    pane is picked up with no keystroke. `r` covers what stat cannot see — a
    tool you just installed, a --help that changed, a binding held by a running
    server.
    """

    def __init__(self):
        self._memo = {}  # (tool, kind, conf) -> (mtime, Reading)

    def read(self, name, ctx):
        kind = kind_for(name)
        if kind is None:
            return None
        # The tool is part of the key because a Reading carries the ctx that
        # produced it, and `help` has no conf file: without it, gh would be
        # answered out of git's cache entry and `children` would run git's
        # subcommands: line.
        key = (ctx.meta.get("name", ""), name, str(ctx.conf))
        now = mtime(ctx.conf)
        hit = self._memo.get(key)
        if hit and hit[0] == now:
            return hit[1]
        try:
            result = kind.read(ctx) or Result.of()
        except Exception as exc:  # a probe must never take the pane down
            result = Result.of(error=str(exc))
        reading = Reading(kind, ctx, result, time.time())
        self._memo[key] = (now, reading)
        return reading

    def invalidate(self, tool=None):
        """Everything, or one tool's worth — which is the difference between
        `R` and `r`."""
        if tool is None:
            self._memo.clear()
            return
        for key in [k for k in self._memo if k[0] == tool]:
            del self._memo[key]


__all__ = [
    "Ctx", "Result", "Kind", "Reading", "Session",
    "add", "join_keys", "lookup", "kind_for",
]
