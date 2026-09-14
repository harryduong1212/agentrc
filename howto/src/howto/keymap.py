"""howto's own keys, read from `hotkeys.toml`.

One table drives dispatch, the always-visible bottom panel AND the `?` overlay,
so howto's advertised keys cannot drift from its real ones — exactly the bug
class this tool exists to fix. Making it a data file does not weaken that: every
surface comes from the single `Keymap` this module builds, and omissions are
reported as config errors rather than hiding working keys.

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
    footer: tuple  # (mode, (action, ...)) pairs
    compact_footer: tuple  # (mode, (action, ...)) pairs
    short: tuple  # (action, compact description) pairs
    compact: tuple  # (action, one-line description) pairs
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

    def resolved_rows(self, configured, labels):
        """Bottom rows resolved from the same entries as dispatch and `?`."""
        by_action = {entry.action: entry for entry in self.entries}
        labels = dict(labels)
        return {
            mode: tuple(
                (spec(by_action[action].keys), labels.get(action, by_action[action].desc))
                for action in actions
                if action in by_action
            )
            for mode, actions in configured
        }

    def footer_rows(self):
        return self.resolved_rows(self.footer, self.short)

    def compact_footer_rows(self):
        return self.resolved_rows(self.compact_footer, self.compact)

    def action_spec(self, action):
        entry = next((entry for entry in self.entries if entry.action == action), None)
        return spec(entry.keys) if entry else ""


def build(data):
    """Pure: a parsed hotkeys.toml in, a Keymap out. No disk, no curses."""
    keys = settings.section(data, "keys")
    desc = settings.section(data, "desc")
    short = settings.section(data, "short")
    compact_spec = settings.section(data, "compact")
    overlay = settings.section(data, "overlay")
    footer_spec = settings.section(data, "footer")
    compact_footer_spec = settings.section(data, "compact_footer")

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
        actions, shown = [], set()
        for action in settings.as_keys(listed):
            action_keys = settings.as_keys(keys.get(action))
            if not action_keys:
                errors.append(f"hotkeys: [footer] {mode} lists '{action}', which has no keys")
                continue
            if action in shown:
                errors.append(f"hotkeys: [footer] {mode} lists '{action}' more than once")
                continue
            shown.add(action)
            actions.append(action)
        missing = [action for action in keys if settings.as_keys(keys[action]) and action not in shown]
        if missing:
            errors.append(f"hotkeys: [footer] {mode} omits {', '.join(missing)}")
        footer[mode] = tuple(actions)
    compact_footer = {}
    for mode, listed in compact_footer_spec.items():
        actions = []
        for action in settings.as_keys(listed):
            if not settings.as_keys(keys.get(action)):
                errors.append(f"hotkeys: [compact_footer] {mode} lists '{action}', which has no keys")
                continue
            actions.append(action)
        compact_footer[mode] = tuple(actions)
    for action, value in short.items():
        if action not in keys:
            errors.append(f"hotkeys: [short] lists unknown action '{action}'")
        elif not isinstance(value, str):
            errors.append(f"hotkeys: [short] '{action}' must be text")
    compact = tuple((action, value) for action, value in short.items() if isinstance(value, str))
    for action, value in compact_spec.items():
        if action not in keys:
            errors.append(f"hotkeys: [compact] lists unknown action '{action}'")
        elif not isinstance(value, str):
            errors.append(f"hotkeys: [compact] '{action}' must be text")
    compact_labels = tuple(
        (action, value) for action, value in compact_spec.items() if isinstance(value, str)
    )
    return Keymap(
        tuple(entries), tuple(footer.items()), tuple(compact_footer.items()), compact,
        compact_labels, tuple(errors)
    )


def load():
    data, errors = settings.load("hotkeys")
    km = build(data)
    return km._replace(errors=tuple(errors) + km.errors)
