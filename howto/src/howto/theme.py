"""The eight colour roles, read from `theme.toml`.

Roles, not colours, everywhere else in the code: `theme.GROUP` is a pair number
that never changes, and what it renders as is the file's business. So a new
theme is a file, and nothing in the drawing code moves.
"""

from . import settings

# Pair numbers. curses reserves 0, so these start at 1.
GROUP, KEY, DIM, SEL, BAR, WARN, OK, TAB = range(1, 9)

ROLES = (
    ("group", GROUP),
    ("key", KEY),
    ("dim", DIM),
    ("sel", SEL),
    ("bar", BAR),
    ("warn", WARN),
    ("ok", OK),
    ("tab", TAB),
)

BASE = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")


def color_number(name, default=-1):
    """A name, a `bright-` name, or a 256-colour number. -1 is the terminal's
    own foreground, which is what `default` means."""
    if isinstance(name, int) and not isinstance(name, bool):
        return name if 0 <= name <= 255 else default
    s = str(name).strip().lower().replace("_", "-")
    if s in ("", "default", "-1"):
        return -1
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 255 else default
    bright, _, base = s.partition("-") if s.startswith("bright-") else ("", "", s)
    if base in BASE:
        return BASE.index(base) + (8 if bright else 0)
    return default


def valid_color(name):
    if isinstance(name, int) and not isinstance(name, bool):
        return 0 <= name <= 255
    value = str(name).strip().lower().replace("_", "-")
    if value in ("", "default", "-1"):
        return True
    if value.isdigit():
        return 0 <= int(value) <= 255
    bright, _, base = value.partition("-") if value.startswith("bright-") else ("", "", value)
    return base in BASE and (not bright or bright == "bright")


def pairs(data):
    """Pure: parsed theme.toml in, [(pair_number, fg)] out."""
    colors = settings.section(data, "colors")
    return tuple((pair, color_number(colors.get(role, "default"))) for role, pair in ROLES)


def load():
    data, errors = settings.load("theme")
    colors = settings.section(data, "colors")
    roles = {role for role, _ in ROLES}
    more = [f"theme: unknown color role '{role}'" for role in colors if role not in roles]
    more.extend(
        f"theme: colors.{role} is not a terminal color"
        for role in roles if role in colors and not valid_color(colors[role])
    )
    return pairs(data), tuple(errors) + tuple(more)


def apply(curses, spec):
    """The one imperative line. Foreground only: the background stays whatever
    the terminal already is, so this reads on a light and a dark theme alike."""
    try:
        curses.use_default_colors()
        for pair, fg in spec:
            curses.init_pair(pair, fg, -1)
        return True
    except curses.error:
        return False  # a terminal with no colour still renders, just flat
