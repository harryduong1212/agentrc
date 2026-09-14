"""`tmux list-keys` needs no server and reports inherited bindings too — 266 on
this machine, against the 9 `bind` lines a grep of the conf would find."""

import shlex

from .. import host
from . import Kind, Result, add, join_keys, lookup

MOUSE = ("Mouse", "Wheel", "DoubleClick", "TripleClick")


def read(ctx):
    base = ["tmux"]
    if ctx.conf and ctx.conf.is_file():
        base += ["-f", str(ctx.conf)]
    out = host.run(base + ["list-keys"], timeout=ctx.timeout)
    if out is None:
        return Result.of(error="tmux not installed, or list-keys refused")
    rows = []
    for line in out.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 3 or parts[0] != "bind-key":
            continue
        tbl, key, rest = split_binding(parts)
        # A mouse binding is not something you can be told to press.
        if rest and not key.startswith(MOUSE):
            rows.append((tbl, key, rest))
    if not rows:
        return Result.of(error="tmux did not report any readable bindings")
    prefix = prefix_key(rows)
    table = {}
    for tbl, key, rest in rows:
        key = key.replace("C-", "Ctrl-").replace("M-", "Alt-")
        label = key if tbl == "root" or not prefix else f"{prefix} {key}"
        add(table, " ".join(rest), label)
        # The bare command name is an alias, but only for the two tables you
        # actually press keys in. Copy mode binds 100 keys to send-keys, and
        # indexing those would make `send-keys` a bucket of every one.
        if tbl in ("prefix", "root"):
            add(table, rest[0], label)
            for name in wrapped(rest):
                add(table, name, label)
    return Result.of(table)


def wrapped(rest):
    """The command a wrapper is really running.

    tmux hides the interesting half of a binding inside a wrapper:
    `command-prompt -I "#S" { rename-session "%%" }` and
    `confirm-before -p "..." kill-window`. Indexing only the first word files
    both of those under command-prompt and confirm-before, where nobody would
    look for them.

    A display-menu is excluded: its braces hold a dozen entries, so indexing
    them files kill-pane under the key that opens the menu.
    """
    if rest[0] == "display-menu":
        return []
    out = [rest[i + 1] for i, t in enumerate(rest[:-1]) if t == "{"]
    if rest[0] == "confirm-before":
        out.append(rest[-1])
    return out


def resolve(table, token, width):
    """Exact first, then longest prefix.

    The binding tmux reports is the whole command with its flags —
    `split-window -h -c "#{pane_current_path}"` — which is not something to
    write in a cheatsheet. `@split-window -h` is enough to name it.
    """
    got = lookup(table, token, width)
    if got:
        return got
    hits = [k for k in table if k.startswith(token + " ")]
    return join_keys(table[min(hits, key=len)], width) if hits else None


def prefix_key(rows):
    """From the bindings themselves. `show-options -gv prefix` needs a running
    server, and without one it answers on stderr — which then gets rendered as
    the key you press."""
    for tbl, key, rest in rows:
        if tbl == "prefix" and rest[0] == "send-prefix":
            return key.replace("C-", "Ctrl-")
    return ""


def split_binding(parts):
    tbl, i = "prefix", 1
    # `len > 1` because `-` is a KEY here, not a flag — this repo's config binds
    # it to the vertical split, and eating it lost that row entirely.
    while i < len(parts) and parts[i].startswith("-") and len(parts[i]) > 1:
        if parts[i] == "-T" and i + 1 < len(parts):
            tbl = parts[i + 1]
            i += 2
            continue
        i += 1
    if i >= len(parts):
        return tbl, "", []
    return tbl, parts[i], parts[i + 1 :]


KIND = Kind("tmux", read, resolve=resolve)
