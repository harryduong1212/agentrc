"""What this machine has that no file describes yet.

Detection is the **filename and the tool**, never the contents. Grepping config
files for `keybind|hotkey|keymap|bind` gave 22 hits here and 1 was real: 21 were
superfile THEME files with a colour setting whose name contains `hotkey`.
Anchoring the pattern to key names still matched those same 21, and then missed
`hotkeys.toml` itself, whose keys are `confirm = [...]`.

Which tools to look for is `tools.toml`, not a table in here — adding helix is a
line in a config file, not a code change. The whole scan costs ~168 ms, which is
why it is a keypress in the view and not a background job with a spinner.
`--help` is not part of it; that stays lazy, one node at a time.
"""

import time
from typing import NamedTuple, Optional

from . import doc, host, settings
from . import probes as probe_pkg

NEW, STALE, SHADOWED, COVERED = "NEW", "STALE", "SHADOWED", "COVERED"


class Tool(NamedTuple):
    name: str
    check: str
    conf: tuple  # candidates, first that exists wins
    probe: str
    view: str


class Found(NamedTuple):
    tool: str
    view: str
    state: str
    target: object
    probe_kind: str
    conf: Optional[object]

    @property
    def writable(self):
        return self.state in (NEW, STALE, SHADOWED)


# ================================================================ the tool table


def known(data):
    """Pure: parsed tools.toml in, the tool table out. Order is the file's."""
    out, errors = [], []
    for name, spec in settings.section(data, "tools").items():
        if not isinstance(spec, dict):
            errors.append(f"tools: [tools.{name}] is not a table")
            continue
        if spec.get("enabled", True) is False:
            continue
        probe = str(spec.get("probe", "")).strip()
        view = str(spec.get("view", "")).strip()
        if not probe:
            errors.append(f"tools: [tools.{name}] has no probe")
            continue
        if view not in doc.VIEWS:
            errors.append(f"tools: [tools.{name}] view must be one of {', '.join(doc.VIEWS)}")
            continue
        check = spec.get("check", "")
        conf = spec.get("conf", "")
        if not isinstance(check, str):
            errors.append(f"tools: [tools.{name}] check must be a string")
            continue
        if not isinstance(conf, (str, list, tuple)):
            errors.append(f"tools: [tools.{name}] conf must be a string or list")
            continue
        out.append(Tool(name, check, settings.as_keys(conf), probe, view))
    return tuple(out), tuple(errors)


def load_known():
    data, errors = settings.load("tools")
    tools, more = known(data)
    return tools, errors + more


def conf_path(candidates):
    """The first candidate that exists. A path starting with `~` is taken as
    written; anything else is relative to the config dir, which is what makes
    one line work on all three OSes."""
    for raw in candidates:
        p = host.expand(raw) if raw.startswith("~") else host.config_root() / raw
        if p and p.is_file():
            return p
    return None


# ======================================================================= the scan


def scan(data_dir, tools=None):
    """One row per tool, not per file — the 22-hits measurement is why."""
    if tools is None:
        tools, _ = load_known()
    have = doc.catalog(data_dir)
    out = []
    for t in tools:
        if t.check and host.which(t.check) is None:
            continue  # not installed here; a shipped file for it still renders
        path = conf_path(t.conf) if t.conf else None
        if t.conf and path is None:
            continue  # nothing to read it out of
        target = host.config_dir() / "generated" / f"{t.name}.{t.view}"
        state = classify(t.name, t.view, have, target, path)
        out.append(Found(t.name, t.view, state, target, t.probe, path))
    return tuple(out)


def classify(tool, view, have, target, conf):
    present = have.get(tool, {}).get(view)
    if present and present[0] == "yours":
        return SHADOWED
    if present and present[0] == "shipped":
        return COVERED
    if target.is_file():
        try:
            if conf and conf.stat().st_mtime > target.stat().st_mtime:
                return STALE
        except OSError:
            pass
        return COVERED
    return NEW


# ======================================================================= the stub


def actions_of(session, f, lay):
    """The live actions for the stub's rows — one tool's worth, read when you
    put the cursor on it. Descriptions stay blank: that is the part a human (or
    another agent) fills in."""
    meta = {"name": f.tool, "probe": f.probe_kind, "conf": str(f.conf) if f.conf else ""}
    reading = session.read(f.probe_kind, probe_pkg.Ctx(f.conf, meta, lay.probe_timeout))
    if reading is None:
        return ()
    if f.probe_kind == "help":
        return tuple(t for t, _, d in reading.children(f.tool) if d >= 0)[: lay.scan_help_actions]
    return tuple(sorted(reading.table))[: lay.scan_key_actions]


def stub_text(f, actions):
    out = [
        f"# Written by howto on {time.strftime('%Y-%m-%d')} from "
        f"{f.conf if f.conf else 'the tool itself'}.",
        "# The actions are live; the descriptions are yours to write.",
        f"# `howto edit {f.tool}` promotes this file, and a re-scan then leaves it alone.",
        f"name:    {f.tool}",
        f"probe:   {f.probe_kind}",
    ]
    if f.conf:
        out.append(f"conf:    {f.conf}")
    out += ["", "= FOUND", ""]
    width = max((len(a) for a in actions), default=8)
    out += [f"@{a.ljust(width)} | " for a in actions]
    return "\n".join(out) + "\n"


def write_stub(f, actions):
    """The only mutating thing the TUI does. It lands in `generated/` and
    nowhere else — never the repo, never a file you wrote. STALE replaces only
    the generated file the scan owns; NEW uses exclusive creation."""
    body = stub_text(f, actions)
    f.target.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if f.state == NEW else "w"
    with f.target.open(mode, encoding="utf-8") as target:
        target.write(body)
    return f.target
