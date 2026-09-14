"""The file format, and the three layers that can hold a copy of one.

Everything here is a pure function over text plus immutable records. Only
`load` and `catalog` touch the disk, and they are one line each — so the parser
can be exercised on a string, and a Doc can be cached without anyone wondering
whether something mutated it since.

A row's open/closed state deliberately does NOT live on the row. It belongs to
the screen you are looking at, not to the file, and keeping it here was what
made the old Doc unsafe to cache.
"""

import os
from typing import NamedTuple

from . import host

HEADER_FIELDS = (
    "name",
    "what",
    "docs",
    "install",
    "check",
    "probe",
    "conf",
    "help_cmd",
    "subcommands",
)

VIEWS = ("keys", "help")


# ================================================================ the records


class Row(NamedTuple):
    """One line of content. `token` is an action when `is_action`, otherwise a
    literal key or command that needs no probe."""

    token: str
    desc: str
    depth: int
    probe_kind: str
    lineno: int
    is_action: bool

    @property
    def expandable(self):
        # Only a --help node has more to read; a keybinding is already the leaf.
        return self.is_action and self.probe_kind == "help"

    def key(self):
        """Identity for the open-node set — stable across a re-render, which an
        object address is not."""
        return (self.lineno, self.token)


class Group(NamedTuple):
    title: str
    probe_kind: str
    rows: tuple


class Doc(NamedTuple):
    meta: dict
    groups: tuple
    path: object
    layer: str
    errors: tuple

    @property
    def name(self):
        return self.meta.get("name") or self.path.stem

    @property
    def view(self):
        return self.path.suffix.lstrip(".")

    @property
    def probe_kind(self):
        return self.meta.get("probe", "")

    @property
    def check(self):
        return self.meta.get("check", "")

    @property
    def present(self):
        # No check: field means it is not a command — the shell's own line
        # editing, a set of aliases. Those are never reported as missing.
        return True if not self.check else host.which(self.check) is not None

    @property
    def conf(self):
        return host.expand(self.meta.get("conf", ""))


# ==================================================================== parsing


def split_row(s):
    r"""Split on the first UNESCAPED `|`; `\|` is a literal pipe.

    Half the useful rows are themselves pipelines (`rg -l x \| xargs sed`), so
    the separator has to be escapable. (None, None) means no separator, which
    is how a header or directive line is recognised.
    """
    key, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            key.append("|")
            i += 2
        elif s[i] == "|":
            return "".join(key).strip(), s[i + 1 :].replace("\\|", "|").strip()
        else:
            key.append(s[i])
            i += 1
    return None, None


def parse_text(text, filename="<string>"):
    """`field: value` header, then `= GROUP` sections of `key | description`.

    Returns (meta, groups, errors). Pure — give it a string, get records back.

    The leading whitespace is measured BEFORE stripping and carried as depth.
    The old parser stripped first, which made a depth-3 flag indistinguishable
    from a depth-1 command.
    """
    meta, groups, errors = {}, [], []
    title, kind, rows = None, "", []

    def close():
        if title is not None or rows:
            groups.append(Group(title or "", kind, tuple(rows)))

    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))

        if stripped.startswith("="):
            close()
            title, kind, rows = stripped.lstrip("=").strip(), meta.get("probe", ""), []
            continue

        field, sep, value = stripped.partition(":")
        field = field.strip()
        # A header field is decided by its name, not by hunting for a `|` — an
        # install line is allowed to be a pipeline.
        if sep and field in HEADER_FIELDS:
            # `probe:` is the one field a group may scope to itself; everything
            # else reaches the header wherever it is written. Dropping a
            # group-level `conf:` left vim's nine mapped rows reading `unbound`.
            if field == "probe" and title is not None:
                kind = value.strip()
            else:
                meta[field] = value.strip()
            continue

        key, desc = split_row(stripped)
        if key is None:
            continue
        if title is None and not rows:
            title, kind = "", meta.get("probe", "")
        if not key and rows:
            # An empty key column continues the description above. Every nested
            # row has a key, so this can never collide with the depth rule —
            # and without it the idiom reads as a row indented eight levels.
            rows[-1] = rows[-1]._replace(desc=rows[-1].desc + " " + desc)
            continue
        depth = indent // 2
        if rows and depth > rows[-1].depth + 1:
            # Reported, not silently reparented: a row indented past its parent
            # is a typo, and guessing where it belongs hides it.
            errors.append(
                f"{filename}:{lineno}: indented to depth {depth} under depth {rows[-1].depth}"
            )
            depth = rows[-1].depth + 1
        # A bare `@` is a key in its own right — it is how you reference a file
        # inside claude — so the marker needs something after it to count.
        action = key.startswith("@") and len(key) > 1
        rows.append(
            Row(key[1:].strip() if action else key, desc, depth, kind, lineno, action)
        )
    close()
    return meta, tuple(groups), tuple(errors)


def load(path, layer="shipped"):
    """parse_text over a file. The only disk read in the parser."""
    meta, groups, errors = parse_text(
        path.read_text(encoding="utf-8", errors="replace"), path.name
    )
    return Doc(meta, groups, path, layer, errors)


# ===================================================================== layers


def layers(data_dir):
    """Highest first. The unit of override is one file — one (tool, view) pair,
    never a merge of rows: a row-level merge is where the surprises live, since
    you would have no way to see which file a line came from."""
    cfg = host.config_dir()
    return (
        ("yours", cfg),
        ("generated", cfg / "generated"),
        ("shipped", data_dir),
    )


def find(data_dir, tool, view):
    """Every layer holding this (tool, view), highest first."""
    out = []
    for name, d in layers(data_dir):
        p = d / f"{tool}.{view}"
        if p.is_file():
            out.append((name, p))
    return out


def catalog(data_dir):
    """tool -> {view: (layer, path)} across all three layers."""
    tools = {}
    for name, d in reversed(layers(data_dir)):  # lowest first, so a higher one wins
        if not d.is_dir():
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            view = p.suffix.lstrip(".")
            if not p.is_file() or view not in VIEWS:
                continue
            tools.setdefault(p.stem, {})[view] = (name, p)
    return tools


def shadow_note(data_dir, tool, view, layer):
    """`yours — overrides generated, shipped`, or just the layer name."""
    stack = find(data_dir, tool, view)
    if len(stack) > 1:
        return layer + " — overrides " + ", ".join(n for n, _ in stack[1:])
    return layer


def mtime(path):
    try:
        return os.stat(path).st_mtime if path else 0
    except OSError:
        return 0
