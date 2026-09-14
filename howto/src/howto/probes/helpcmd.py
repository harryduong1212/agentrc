"""`<cmd> --help`: flags AND subcommands, one node at a time.

Both halves, because a flag-only read reports git as 4 rows. One node, because
20 `git <sub> --help` calls took 1847 ms — git's 178 subcommands would be ~16 s,
so the tree is never walked, only the node you opened.
"""

import re
import shlex

from .. import host
from . import Kind, Result

OVERSTRIKE = re.compile(r".\x08")


def read(ctx):
    # Nothing to cache: the command IS the key. The table stays empty and
    # `resolve` answers from the token, which is why this probe costs 0 ms
    # until you open a node.
    return Result.of()


def resolve(table, token, width=None):
    # Never None: `unbound` on a help row would hide the command, and whether
    # the binary is here is already on the panel header from `check:`.
    return token


def children(ctx, token):
    outputs = [host.run(cmd, timeout=ctx.timeout) for cmd in help_cmds(ctx, token)]
    outputs = [out for out in outputs if out is not None]
    if not outputs:
        return [("(--help produced nothing)", "", 0)]
    flags, subs = (), ()
    for out in outputs:
        found_flags, found_subs = parse_help(out)
        flags = unique(flags + tuple(found_flags))
        subs = unique(subs + tuple(found_subs))
    rows = []
    if subs:
        rows.append(("SUBCOMMANDS", "", -1))
        rows += [(n, d, 0) for n, d in subs]
    if flags:
        # Curated groups render first; this one goes last, so rg's 149 flags are
        # reachable without being the first thing you see.
        rows.append(("ALL FLAGS (from --help)", "", -1))
        rows += [(n, d, 0) for n, d in flags]
    return rows or [("(no flags or subcommands found)", "", 0)]


def unique(rows):
    out, seen = [], set()
    for name, desc in rows:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, desc))
    return tuple(out)


def help_cmds(ctx, token):
    primary = help_cmd(ctx, token)
    parts = shlex.split(token)
    if ctx.meta.get("subcommands") and len(parts) == 1:
        return (parts + ["--help"], primary)
    return (primary,)


def help_cmd(ctx, token):
    parts = shlex.split(token)
    # `subcommands:` exists because `git --help` lists 4 flags while
    # `git help -a` lists 178 subcommands. Which command to ask is a fact about
    # the tool, so it lives in the tool's file, not in here.
    override = ctx.meta.get("subcommands", "")
    if override and len(parts) == 1:
        return shlex.split(override)
    tmpl = ctx.meta.get("help_cmd", "")
    if tmpl:
        return shlex.split(tmpl.replace("{}", token))
    return parts + ["--help"]


def parse_help(text):
    """(flags, subcommands) out of a --help dump.

    Shape-based on purpose: a flag is a line whose first word starts with `-`, a
    subcommand is an indented bare word under a heading that says commands.
    Anything cleverer becomes a table of per-tool special cases.
    """
    # `less` underlines with the nroff `_\bX` overstrike — 86 of its lines carry
    # it, and read literally `-<flag>` comes out as `-_<_f_l_a_g_>`. It is the
    # only tool here that does it, but stripping costs nothing on the others.
    text = OVERSTRIKE.sub("", text)
    flags, subs, in_cmds = [], [], False
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.lower().startswith("usage:"):
            flags.extend(usage_flags(raw))
            continue
        if not raw.startswith((" ", "\t")):
            low = raw.strip().lower().rstrip(":")
            in_cmds = (
                low.endswith("commands")
                or " commands / " in low
                or "interfaces" in low
                or low == "external commands"
                or low == "interacting with others"
                or low == "command aliases"
            )
            continue
        s = raw.strip()
        first = s.split()[0]
        name, _, rest = s.partition("  ")
        indent = len(raw) - len(raw.lstrip(" \t"))
        if first.startswith("-") and first != "--" and indent <= 6:
            # `less --help` draws 11 rules of dashes between its sections, and a
            # bare `startswith("-")` read every one of them as a flag.
            flags.append((name.strip().rstrip(","), rest.strip()))
        elif (
            in_cmds
            and indent <= 3
            and first.replace("-", "_").isidentifier()
        ):
            subs.append((name.strip(), rest.strip()))
    return flags, subs


def usage_flags(line):
    seen = []
    for match in re.finditer(r"(?<!\w)(--?[A-Za-z][A-Za-z0-9-]*)", line):
        flag = match.group(1)
        if flag not in seen:
            seen.append(flag)
    return [(flag, "") for flag in seen]


KIND = Kind("help", read, resolve=resolve, children=children)
