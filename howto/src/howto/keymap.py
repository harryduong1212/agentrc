"""howto's own keys, read from `hotkeys.toml`.

One table drives dispatch AND the `?` overlay, so howto's advertised keys cannot
drift from its real ones — which is exactly the bug class this tool exists to
fix. Making it a data file does not weaken that: both still come from the single
`Keymap` this module builds, and an action in `[keys]` that no section lists is
reported as a config error rather than dispatching a key nothing tells you
about.

Symbolic names live here and not in the TOML on purpose. `esc` being 27 is a
fact about terminals, not a preference; what is configurable is which of them
you bind.
"""

from typing import NamedTuple

from . import settings

# Filled by `names(curses)` — curses is imported by the app, not by this module,
# because on Windows it is a pip install away and `howto --list` must work
# without it.
_NAMED = {}


class _Symbols:
    def __getattr__(self, name):
        return 0


def names(curses):
    """The symbolic vocabulary a hotkeys file may use."""
    named = {
        "tab": (9,),
        "enter": (10, 13, curses.KEY_ENTER),
        "esc": (27,),
        "space": (32,),
        "backspace": (curses.KEY_BACKSPACE, 127, 8),
        "up": (curses.KEY_UP,),
        "down": (curses.KEY_DOWN,),
        "left": (curses.KEY_LEFT,),
        "right": (curses.KEY_RIGHT,),
        "pgup": (curses.KEY_PPAGE,),
        "pgdown": (curses.KEY_NPAGE,),
        "home": (curses.KEY_HOME,),
        "end": (curses.KEY_END,),
        "shift+left": (curses.KEY_SLEFT,),
        "shift+right": (curses.KEY_SRIGHT,),
        "shift+up": (curses.KEY_SR,),
        "shift+down": (curses.KEY_SF,),
    }
    for i in range(1, 13):
        named[f"f{i}"] = (getattr(curses, f"KEY_F{i}"),)
    for c in "abcdefghijklmnopqrstuvwxyz":
        named[f"ctrl+{c}"] = (ord(c) - 96,)
    return named


def bind(curses):
    """Teach this module what the terminal calls its keys. Idempotent."""
    global _NAMED
    if not _NAMED:
        _NAMED = names(curses)
    return _NAMED


def named():
    """The symbolic table, after `bind`. Empty before it — the search box asks
    for `esc` and `backspace` by name, and those are terminal facts."""
    return _NAMED


def codes(keys):
    """['tab', 'L'] -> the integers curses will actually deliver.

    An unknown name yields nothing rather than raising: a typo in your hotkeys
    file costs you that binding, reported at load, not the whole app.
    """
    out = []
    for k in keys:
        k = k.strip()
        if k in _NAMED:
            out.extend(_NAMED[k])
        elif len(k) == 1:
            out.append(ord(k))
    return tuple(out)


def spec(keys):
    """How the `?` overlay writes a binding: 'tab, L'."""
    return ", ".join(keys)


class Entry(NamedTuple):
    action: str
    keys: tuple
    desc: str
    section: str


class Keymap(NamedTuple):
    entries: tuple  # in overlay order — sections, then actions within them
    footer: tuple  # (mode, ((action, short label), ...)) pairs
    errors: tuple

    def dispatch(self):
        """key code -> action. First binding wins, so an action you rebind onto
        a key another action already holds is reported, not silently swapped."""
        table = {}
        for e in self.entries:
            for c in codes(e.keys):
                table.setdefault(c, e.action)
        return table

    def rows(self):
        """(section, spec, desc, action) — what the overlay renders."""
        return tuple((e.section, spec(e.keys), e.desc, e.action) for e in self.entries)

    def actions(self):
        return tuple(e.action for e in self.entries)

    def footer_rows(self):
        """Footer actions resolved from the same entries as dispatch."""
        by_action = {entry.action: entry.keys for entry in self.entries}
        return {
            mode: tuple((by_action[action][0], label) for action, label in rows)
            for mode, rows in self.footer
        }


def build(data):
    """Pure: a parsed hotkeys.toml in, a Keymap out. No disk, no curses."""
    keys = settings.section(data, "keys")
    desc = settings.section(data, "desc")
    overlay = settings.section(data, "overlay")
    short = settings.section(data, "short")
    footer_spec = settings.section(data, "footer")

    errors, entries, placed, claimed = [], [], set(), {}
    allowed = set(names(_Symbols()))
    for action, value in keys.items():
        if not isinstance(value, (str, list, tuple)):
            errors.append(f"hotkeys: [keys] '{action}' must be a key or list")
            continue
        for key in settings.as_keys(value):
            if len(key) != 1 and key not in allowed:
                errors.append(f"hotkeys: [keys] '{action}' has unknown key '{key}'")
            owner = claimed.setdefault(key, action)
            if owner != action:
                errors.append(f"hotkeys: key '{key}' is bound to both '{owner}' and '{action}'")
    for section, listed in overlay.items():
        for action in settings.as_keys(listed):
            if action in placed:
                errors.append(f"hotkeys: '{action}' is listed in more than one section")
                continue
            if action not in keys:
                errors.append(f"hotkeys: [overlay] lists '{action}', which has no keys")
                continue
            action_keys = settings.as_keys(keys[action])
            if not action_keys:
                errors.append(f"hotkeys: [overlay] lists '{action}', which has no keys")
                continue
            placed.add(action)
            wording = desc.get(action, "")
            if not isinstance(wording, str):
                errors.append(f"hotkeys: [desc] '{action}' must be text")
                wording = ""
            entries.append(Entry(action, action_keys, wording, section))
    for action in keys:
        if action not in placed:
            # Not cosmetic: an unlisted action is a key howto answers to and
            # never tells you about, which is the drift this tool exists to
            # catch. It still dispatches — it is just no longer silent.
            action_keys = settings.as_keys(keys[action])
            if not action_keys:
                continue
            errors.append(f"hotkeys: '{action}' is bound but no [overlay] section lists it")
            wording = desc.get(action, "")
            if not isinstance(wording, str):
                errors.append(f"hotkeys: [desc] '{action}' must be text")
                wording = ""
            entries.append(Entry(action, action_keys, wording, "other"))
    footer = {}
    for mode, listed in footer_spec.items():
        rows = []
        for action in settings.as_keys(listed):
            action_keys = settings.as_keys(keys.get(action))
            if not action_keys:
                errors.append(f"hotkeys: [footer.{mode}] lists '{action}', which has no keys")
                continue
            label = short.get(action, action)
            if not isinstance(label, str):
                errors.append(f"hotkeys: [short] '{action}' must be text")
                label = action
            rows.append((action, label))
        footer[mode] = tuple(rows)
    return Keymap(tuple(entries), tuple(footer.items()), tuple(errors))


def load():
    data, errors = settings.load("hotkeys")
    km = build(data)
    return km._replace(errors=tuple(errors) + km.errors)
