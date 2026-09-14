"""What the two panes hold.

`ui.Item` is the sentinel protocol from spf's sidebar: `can_focus` is what stops
the cursor landing on a divider, and `required_height` is what stops a wrapped
description being scrolled past. Everything specific to howto's content is here,
so `ui.py` stays content-agnostic and reusable.
"""

from . import ui
from .scan import COVERED
from .theme import DIM


class ToolItem(ui.Item):
    def __init__(self, name, views, fav, present):
        self.name = name
        self.views = views  # {view: (layer, path)}
        self.fav = fav
        self.present = present

    def marks(self):
        return ("K" if "keys" in self.views else "·") + ("H" if "help" in self.views else "·")

    def search_text(self):
        return self.name


class RowItem(ui.Item):
    """A content row, already resolved against the probe."""

    def __init__(self, row, keytext, resolved, lines):
        self.row = row
        self.keytext = keytext
        self.resolved = resolved
        self.lines = lines  # the wrapped description

    def required_height(self):
        return max(1, len(self.lines))

    def search_text(self):
        return f"{self.keytext} {self.row.token} {self.row.desc}"


class NoteItem(ui.Item):
    """A line that is not content — a probe failure, an empty-view hint."""

    def __init__(self, text, pair=DIM):
        self.text = text
        self.pair = pair

    def can_focus(self):
        return False

    def search_text(self):
        return self.text


class ScanItem(ui.Item):
    def __init__(self, found):
        self.found = found
        self.marked = False

    def can_focus(self):
        # A COVERED row has nothing to do, so it refuses the cursor the same way
        # a divider does — one code path, ui.Pane.cursor_is_invalid.
        return self.found.state != COVERED

    def search_text(self):
        return f"{self.found.tool} {self.found.state} {self.found.probe_kind}"
