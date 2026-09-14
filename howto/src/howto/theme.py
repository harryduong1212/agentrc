"""The display colour roles, read from `theme.toml`.

Roles, not colours, everywhere else in the code: `theme.GROUP` is a pair number
that never changes, and what it renders as is the file's business. So a new
theme is a file, and nothing in the drawing code moves.
"""

import re
from typing import NamedTuple

from . import settings

# Pair numbers. curses reserves 0, so these start at 1.
TEXT, GROUP, KEY, DIM, SEL, BAR, WARN, OK, TAB, BORDER = range(1, 11)

ROLES = (
    ("text", TEXT),
    ("group", GROUP),
    ("key", KEY),
    ("dim", DIM),
    ("sel", SEL),
    ("bar", BAR),
    ("warn", WARN),
    ("ok", OK),
    ("tab", TAB),
    ("border", BORDER),
)

BASE = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
ANSI_RGB = (
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)


class Palette(NamedTuple):
    pairs: tuple
    errors: tuple


def xterm_rgb(number):
    """The RGB represented by one xterm-256 palette index."""
    if 0 <= number < 16:
        return ANSI_RGB[number]
    if 16 <= number <= 231:
        value = number - 16
        levels = (0, 95, 135, 175, 215, 255)
        return levels[value // 36], levels[(value // 6) % 6], levels[value % 6]
    shade = 8 + 10 * max(0, min(23, number - 232))
    return shade, shade, shade


def nearest_xterm(rgb, choices=range(16, 256)):
    """Nearest available palette entry; terminals expose indexed, not RGB, curses."""
    return min(
        choices,
        key=lambda number: sum((left - right) ** 2 for left, right in zip(rgb, xterm_rgb(number))),
    )


def color_number(name, default=-1):
    """A name, RGB hex, or 256-colour number. `default` uses the terminal's color."""
    if isinstance(name, int) and not isinstance(name, bool):
        return name if 0 <= name <= 255 else default
    s = str(name).strip().lower().replace("_", "-")
    if s in ("", "default", "-1"):
        return -1
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 255 else default
    if HEX.fullmatch(s):
        rgb = tuple(int(s[index:index + 2], 16) for index in (1, 3, 5))
        return nearest_xterm(rgb)
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
    if HEX.fullmatch(value):
        return True
    bright, _, base = value.partition("-") if value.startswith("bright-") else ("", "", value)
    return base in BASE and (not bright or bright == "bright")


def pairs(data):
    """Pure: parsed theme.toml in, [(pair_number, fg, bg)] out."""
    colors = settings.section(data, "colors")
    background = color_number(colors.get("background", "default"))
    return tuple(
        (pair, color_number(colors.get(role, "default")), background)
        for role, pair in ROLES
    )


def load():
    data, errors = settings.load("theme")
    colors = settings.section(data, "colors")
    roles = {role for role, _ in ROLES} | {"background"}
    more = [f"theme: unknown color role '{role}'" for role in colors if role not in roles]
    more.extend(
        f"theme: colors.{role} is not a terminal color"
        for role in roles if role in colors and not valid_color(colors[role])
    )
    return Palette(pairs(data), tuple(errors) + tuple(more))


def available_color(number, total):
    """Fit a 256-colour result to terminals that expose only 8 or 16 colours."""
    if number < 0 or number < total:
        return number
    if total <= 0:
        return -1
    choices = range(min(total, 16))
    return nearest_xterm(xterm_rgb(number), choices)


def apply(curses, spec):
    """Install the configured foreground/background pairs in this terminal."""
    try:
        curses.use_default_colors()
        total = getattr(curses, "COLORS", 256)
        for pair, fg, bg in spec:
            curses.init_pair(pair, available_color(fg, total), available_color(bg, total))
        return True
    except curses.error:
        return False  # a terminal with no colour still renders, just flat
