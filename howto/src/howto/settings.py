"""Four data files, four concerns, two layers each.

| file | holds |
|---|---|
| `hotkeys.toml` | every action's keys, its wording, and which section of `?` it sits in |
| `tools.toml`   | what SCAN knows how to look for |
| `theme.toml`   | the eight colour roles |
| `config.toml`  | the sizes and timeouts |

The shipped copy under `howto/config/` is the **only** source of truth — there
is no second copy of these tables in Python, so a default cannot drift from what
the file says. Your `~/.config/howto/<name>.toml` merges over it, table by table
and key by key, so overriding one hotkey does not cost you the other 23.

`tomllib` is stdlib from 3.11, which is why `pyproject.toml` asks for 3.11.
Making the defaults a data file only works if reading that file is free.
"""

import tomllib
from pathlib import Path
from importlib import resources

from . import host

# Wheels install these as ordinary files, so callers can pass real paths to
# editors and subprocesses without extracting a resource first.
PKG = Path(str(resources.files(__package__)))
SHIPPED = PKG / "config"
DATA = PKG / "data"  # the shipped catalog — doc.layers()' lowest layer
TEMPLATES = PKG / "templates"

NAMES = ("hotkeys", "tools", "theme", "config")
TOP_LEVEL = {
    "hotkeys": ("keys", "desc", "short", "footer", "overlay"),
    "tools": ("tools",),
    "theme": ("colors",),
    "config": ("layout", "probe", "scan"),
}


def read_toml(path):
    """(data, error). A malformed file is a message, never a traceback — a typo
    in your hotkeys must not stop howto from opening."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh), ""
    except FileNotFoundError:
        return {}, ""
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, f"{path}: {exc}"


def merge(base, over):
    """Tables merge, everything else replaces.

    A list replaces rather than extends on purpose: rebinding `quit` to `Q`
    should give you `Q`, not `q, esc, Q`. Removing a key you do not want would
    otherwise be impossible.
    """
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def load(name):
    """(data, errors) for one concern, shipped defaults under your overrides."""
    base, e1 = read_toml(SHIPPED / f"{name}.toml")
    over, e2 = read_toml(host.config_dir() / f"{name}.toml")
    errors = [error for error in (e1, e2) if error]
    allowed = TOP_LEVEL.get(name, ())
    errors.extend(f"{name}: unknown top-level table '{key}'" for key in over if key not in allowed)
    return merge(base, over), tuple(errors)


def user_path(name):
    return host.config_dir() / f"{name}.toml"


def shipped_path(name):
    return SHIPPED / f"{name}.toml"


# ============================================================== typed readers


def section(data, name, default=None):
    v = data.get(name)
    return v if isinstance(v, dict) else (default if default is not None else {})


def as_keys(v):
    """One key or a list of them — `quit = "q"` and `quit = ["q", "esc"]` both
    read, because insisting on a list for the single-key case is a papercut."""
    if isinstance(v, str):
        return (v,)
    if isinstance(v, (list, tuple)):
        return tuple(str(x) for x in v if str(x).strip())
    return ()


def as_int(data, key, default=None):
    v = data.get(key, default)
    return v if isinstance(v, int) and not isinstance(v, bool) else default
