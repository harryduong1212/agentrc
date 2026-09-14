#!/usr/bin/env python3
"""The pane: a flat list of items, a cursor that skips structure, height-aware
scrolling, and a filter that keeps structure and then prunes what it emptied.

This is superfile's sidebar/helpmenu contract, in Python. It is not "spf-like";
each piece below names the file it came from, because the point of copying it
was to inherit the four bugs it has already fixed:

  sidebar/utils.go   isDivider / isCursorInvalid / resetCursor
                     -> separators live in the item list, the cursor refuses them
  sidebar/utils.go   pinnedIndexRange
                     -> block bounds come from the DISPLAYED list, since search
                        shortens it (spf's own comment says so)
  sidebar/utils.go   requiredHeight + sidebar/render.go loop
                     -> stop scrolling when the next item's height will not fit,
                        rather than assuming one line per item
  helpmenu/data.go   removeOrphanSections / filter
                     -> after filtering, drop a header whose children all went;
                        put the cursor back on a real row, reset the scroll

Nothing here knows what a keybinding is. The app supplies the items.
"""

import curses

# --------------------------------------------------------------------- items


class Item:
    """One row. The pane needs only these three answers from it."""

    def is_separator(self):
        """True for structure — a divider or a section header."""
        return False

    def is_section(self):
        """True for a header that should vanish when it has no children left."""
        return False

    def can_focus(self):
        """Whether the cursor may land here. Structure never can."""
        return not self.is_separator()

    def required_height(self):
        """Terminal lines this row needs. sidebar/utils.go requiredHeight."""
        return 1

    def search_text(self):
        """The haystack for filter(). helpmenu/data.go joins key + description."""
        return ""


class Divider(Item):
    """A block boundary — favourites from the rest. spf's dividerDirHeight is 3:
    a blank line, the rule, a blank line."""

    def __init__(self, label="", height=3):
        self.label = label
        self.height = height

    def is_separator(self):
        return True

    def required_height(self):
        return self.height


class Header(Item):
    """A section title. Skipped by the cursor, and pruned when emptied."""

    def __init__(self, title, blank_before=True):
        self.title = title
        self.blank_before = blank_before

    def is_separator(self):
        return True

    def is_section(self):
        return True

    def required_height(self):
        return 2 if self.blank_before else 1


# -------------------------------------------------------------------- search


def fuzzy_score(query, text):
    """Score `text` against `query` as a subsequence, or None if it is not one.

    A stand-in for spf's utils.FzfSearch, which is a real fzf port. Same two
    things fzf rewards, because they are what make ranking feel right: a run of
    consecutive characters, and a match that starts a word. Case-insensitive.
    """
    if not query:
        return 0
    q, t = query.lower(), text.lower()
    score, qi, run = 0, 0, 0
    for i, ch in enumerate(t):
        if qi < len(q) and ch == q[qi]:
            score += 1
            run += 1
            score += run  # a consecutive run is worth more than scattered hits
            if i == 0 or t[i - 1] in " \t-_/.,|":
                score += 4
            qi += 1
        else:
            run = 0
    if qi < len(q):
        return None
    return score - len(t) * 0.01  # nudge shorter matches ahead of longer ones


def prune_orphan_sections(items):
    """Drop a header whose children were all filtered away.

    helpmenu/data.go removeOrphanSections. Filtering keeps every header so the
    structure survives, which leaves headers standing over nothing; this is the
    second pass that removes them. Looks ahead rather than counting, so nested
    headers collapse from the inside out.
    """
    out = []
    for i, it in enumerate(items):
        if it.is_section():
            # Keep it only if something focusable follows before the next header.
            for nxt in items[i + 1 :]:
                if nxt.is_section():
                    break
                if nxt.can_focus():
                    out.append(it)
                    break
        else:
            out.append(it)
    return out


def filter_block(block, query):
    """Filter a headerless block, preserving non-section sentinels."""
    return [
        item for item in block
        if item.is_separator() or fuzzy_score(query, item.search_text()) is not None
    ]


def keep_ancestors(block, hits):
    """Keep each nested hit's parents; RowItem supplies the depth."""
    hit_ids = {id(item) for item in hits}
    keep = set(hit_ids)
    stack, all_items = [], []
    for item in block:
        row = getattr(item, "row", None)
        if row is None:
            continue
        while stack and stack[-1].row.depth >= row.depth:
            stack.pop()
        all_items.append((item, tuple(stack)))
        stack.append(item)
    for item, parents in all_items:
        if id(item) not in hit_ids:
            continue
        keep.update(id(parent) for parent in parents)
        for candidate, candidate_parents in all_items:
            if len(candidate_parents) < len(parents) + 1:
                continue
            if candidate_parents[: len(parents)] == parents and candidate_parents[len(parents)] is item:
                keep.add(id(candidate))
    return [item for item in block if id(item) in keep]


# ---------------------------------------------------------------------- pane


class Pane:
    """sidebar/type.go and helpmenu/type.go are the same shape; so is this.

    Both of spf's panes carry {width, height, renderIndex, cursor, data,
    filteredData, searchBar}. Sharing the shape is what lets one set of cursor
    and scroll rules serve every pane, instead of each growing its own.
    """

    def __init__(self, title=""):
        self.title = title
        self.items = []
        self.filtered = []
        self.cursor = 0
        self.render_index = 0
        self.width = 0
        self.height = 0
        self.query = ""
        self.searching = False

    # ---- contents

    def set_items(self, items, keep_cursor=False):
        self.items = items
        old = self.cursor
        self.apply_filter(self.query)
        if keep_cursor and 0 <= old < len(self.filtered):
            self.cursor = old
            if self.cursor_is_invalid():
                self.reset_cursor()

    @property
    def rows(self):
        return self.filtered

    def current(self):
        if self.cursor_is_invalid():
            return None
        return self.filtered[self.cursor]

    # ---- the cursor. sidebar/utils.go

    def no_focusable(self):
        """True when the list is only structure. sidebar/utils.go NoActualDir."""
        return not any(it.can_focus() for it in self.filtered)

    def cursor_is_invalid(self):
        """Out of bounds, or sitting on something that refuses focus."""
        return (
            self.cursor < 0
            or self.cursor >= len(self.filtered)
            or not self.filtered[self.cursor].can_focus()
        )

    def reset_cursor(self):
        """First focusable row, or 0 if there is none."""
        self.cursor = 0
        for i, it in enumerate(self.filtered):
            if it.can_focus():
                self.cursor = i
                return

    def move(self, delta):
        """Step `delta` focusable rows, stopping at the ends rather than wrapping.

        Wrapping is wrong here: with favourites on top, wrapping from the last
        tool lands you in the favourites block, which reads as a glitch.
        """
        if not self.filtered or self.no_focusable():
            return
        step = 1 if delta > 0 else -1
        remaining = abs(delta)
        i = self.cursor
        while remaining:
            j = i + step
            while 0 <= j < len(self.filtered) and not self.filtered[j].can_focus():
                j += step
            if not (0 <= j < len(self.filtered)):
                break
            i = j
            remaining -= 1
        self.cursor = i
        self.follow_cursor()

    def to_edge(self, last):
        if not self.filtered:
            return
        self.cursor = len(self.filtered) - 1 if last else 0
        if self.cursor_is_invalid():
            # Walk inward to the nearest focusable row.
            step = -1 if last else 1
            i = self.cursor
            while 0 <= i < len(self.filtered) and not self.filtered[i].can_focus():
                i += step
            if 0 <= i < len(self.filtered):
                self.cursor = i
        self.follow_cursor()

    # ---- scrolling. sidebar/render.go, which breaks on height not on count

    def fits(self, start, height):
        """How many items from `start` fit in `height` lines."""
        total, n = 0, 0
        for it in self.filtered[start:]:
            h = it.required_height()
            if total + h > height:
                break
            total += h
            n += 1
        return n

    def visible(self, height):
        """The slice to draw, and the index it starts at."""
        self.render_index = max(0, min(self.render_index, max(0, len(self.filtered) - 1)))
        n = self.fits(self.render_index, height)
        return self.render_index, self.filtered[self.render_index : self.render_index + n]

    def follow_cursor(self, height=None):
        """Pull render_index until the cursor is inside the drawn window."""
        h = height if height is not None else self.height
        if h <= 0 or not self.filtered:
            return
        if self.cursor < self.render_index:
            self.render_index = self.cursor
            return
        # Advance one item at a time; each has its own height, so there is no
        # arithmetic shortcut here.
        guard = 0
        while self.cursor >= self.render_index + self.fits(self.render_index, h):
            self.render_index += 1
            guard += 1
            if guard > len(self.filtered):
                break

    def scroll_by(self, delta, height=None):
        h = height if height is not None else self.height
        self.render_index = max(0, min(self.render_index + delta, max(0, len(self.filtered) - 1)))
        # Keep the cursor on screen so the next j/k does not jump back.
        n = self.fits(self.render_index, h)
        if self.cursor < self.render_index or self.cursor >= self.render_index + n:
            self.cursor = self.render_index
            if self.cursor_is_invalid():
                for i in range(self.render_index, min(self.render_index + n, len(self.filtered))):
                    if self.filtered[i].can_focus():
                        self.cursor = i
                        break

    # ---- filtering. helpmenu/data.go filter

    def apply_filter(self, query):
        """Keep structure, score the rest, then drop the headers left childless."""
        self.query = query
        if not query:
            self.filtered = list(self.items)
        else:
            kept = []
            headers = [i for i, item in enumerate(self.items) if item.is_section()]
            first = headers[0] if headers else len(self.items)
            kept.extend(filter_block(self.items[:first], query))
            for pos, i in enumerate(headers):
                it = self.items[i]
                end = headers[pos + 1] if pos + 1 < len(headers) else len(self.items)
                block = self.items[i + 1:end]
                hits = [row for row in block if row.can_focus() and fuzzy_score(query, row.search_text()) is not None]
                if hits:
                    kept.append(it)
                    kept.extend(keep_ancestors(block, hits))
            self.filtered = prune_orphan_sections(kept)
        self.render_index = 0
        self.reset_cursor()

    # ---- the block bounds of a leading section. sidebar/utils.go pinnedIndexRange

    def block_range(self, divider):
        """(start, end) of the rows before `divider`, from the DISPLAYED list.

        spf computes this from s.directories rather than from the source, and
        says why in a comment: in search mode the displayed list is shorter, so
        a bound taken from the source points at the wrong row.
        """
        idx = -1
        for i, it in enumerate(self.filtered):
            if it is divider:
                idx = i
                break
        if idx <= 0:
            return -1, -1
        return 0, idx - 1


# ------------------------------------------------------------------- drawing


def put(win, y, x, text, attr=0):
    """addstr that clips at the edges instead of raising."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w - 1 or x < 0:
        return
    try:
        win.addstr(y, x, text[: w - x - 1], attr)
    except curses.error:
        pass


def wrap(text, width):
    if width < 4:
        return [text]
    out, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return out + [cur] if cur else out or [""]


def search_bar_visible(pane, pane_focused):
    """sidebar/render.go line 23: drawn only when focused, non-empty, or its
    pane has focus. A permanently reserved line is one line of content lost on
    every screen, for a box you are not using."""
    return pane.searching or pane.query != "" or pane_focused
