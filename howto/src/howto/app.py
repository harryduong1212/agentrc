"""The curses browser: mutable screen state around immutable content records."""

import curses
import time

from . import doc, favorites, items, keymap, layout, probes, scan, settings, theme, ui


class App:
    def __init__(self, startup_errors=()):
        self.left = ui.Pane("tools")
        self.right = ui.Pane("content")
        self.scanpane = ui.Pane("found")
        self.view = "keys"
        self.mode = "view"
        self.focus = "left"
        self.active_tool = ""
        self.overlay = False
        self.overlay_at = 0
        self.hotkey_at = 0
        self.hotkey_page = 1
        self.full_footer = True
        self.status = ""
        self.docs = {}
        self.open = set()
        self.kids = {}
        self.session = probes.Session()
        self.select_mode = False
        self.found = ()
        self.scan_actions = {}  # (tool, view) -> actions
        self.divider = ui.Divider("favourites", height=1)

        self.km = keymap.load()
        self.lay, layout_errors = layout.load()
        self.known, scan_errors = scan.load_known()
        self.dispatch = self.km.dispatch()
        self.errors = list(startup_errors + self.km.errors + layout_errors + scan_errors)
        self.favs = ()
        self.reload()
        self.show_errors()

    def show_errors(self):
        if self.errors:
            more = len(self.errors) - 1
            self.status = self.errors[0] + (f" (+{more} more; ? for all)" if more else "")

    def add_errors(self, errors):
        fresh = [error for error in errors if error not in self.errors]
        if fresh:
            self.errors.extend(fresh)
            self.show_errors()

    # ---------------------------------------------------------------- model

    def reload(self):
        selected = self.current_tool()
        selected_name = selected.name if selected else ""
        self.cat = doc.catalog(settings.DATA)
        names = sorted(self.cat)
        self.favs = favorites.load(set(names))
        top = [name for name in names if name in self.favs]
        rest = [name for name in names if name not in self.favs]
        rows = [self.tool_item(name) for name in top]
        if top and rest:
            rows.append(self.divider)
        rows.extend(self.tool_item(name) for name in rest)
        self.left.set_items(rows, keep_cursor=True)
        if selected_name:
            for index, item in enumerate(self.left.rows):
                if isinstance(item, items.ToolItem) and item.name == selected_name:
                    self.left.cursor = index
                    break
        self.refresh_right()

    def tool_item(self, name):
        views = self.cat.get(name, {})
        present = True
        for view in doc.VIEWS:
            if view in views:
                loaded = self.get_doc(name, view)
                present = loaded.present if loaded else True
                break
        return items.ToolItem(name, views, name in self.favs, present)

    def get_doc(self, tool, view):
        key = (tool, view)
        if key not in self.docs:
            entry = self.cat.get(tool, {}).get(view)
            if not entry:
                self.docs[key] = None
            else:
                layer_name, path = entry
                try:
                    loaded = doc.load(path, layer_name)
                except OSError as exc:
                    self.docs[key] = None
                    self.add_errors((f"{path}: {exc}",))
                    return None
                self.docs[key] = loaded
                self.add_errors(loaded.errors)
        return self.docs[key]

    def reading(self, loaded, kind):
        if not loaded or not kind:
            return None
        return self.session.read(kind, probes.Ctx.of(loaded, self.lay.probe_timeout))

    def current_tool(self):
        item = self.left.current()
        return item if isinstance(item, items.ToolItem) else None

    def node_key(self, loaded, row):
        return (loaded.name, loaded.view) + row.key()

    # --------------------------------------------------------- content pane

    def refresh_right(self):
        tool = self.current_tool()
        if tool is None:
            self.active_tool = ""
            self.right.set_items([items.NoteItem("no tools found")])
            return
        self.active_tool = tool.name
        loaded = self.get_doc(tool.name, self.view)
        if loaded is None:
            self.right.set_items(self.template_hint(tool.name))
            return
        current = self.right.current()
        identity = self.row_identity(current)
        self.right.set_items(self.build_rows(loaded))
        if self.focus == "right":
            self.restore_right_cursor(identity)
        if self.right.query:
            self.apply_right_filter(loaded, self.right.query)

    def row_identity(self, item):
        if not isinstance(item, items.RowItem):
            return None
        return item.row.lineno, item.row.token, item.keytext

    def restore_right_cursor(self, identity):
        if identity is None:
            return
        for index, item in enumerate(self.right.rows):
            if self.row_identity(item) == identity:
                self.right.cursor = index
                self.right.follow_cursor()
                return

    def open_matching_ancestors(self, loaded, query):
        for item in self.right.rows:
            if (
                not isinstance(item, items.RowItem)
                or ui.fuzzy_score(query, item.search_text()) is None
            ):
                continue
            for group in loaded.groups:
                parents = []
                for row in group.rows:
                    while parents and parents[-1].depth >= row.depth:
                        parents.pop()
                    if row.key() == item.row.key():
                        self.open.update(self.node_key(loaded, parent) for parent in parents)
                        break
                    parents.append(row)

    def apply_right_filter(self, loaded, query):
        self.right.set_items(self.build_rows(loaded))
        self.right.apply_filter(query)
        self.open_matching_ancestors(loaded, query)
        self.right.set_items(self.build_rows(loaded))
        self.right.apply_filter(query)

    def template_hint(self, tool):
        target = doc.layers(settings.DATA)[0][1] / f"{tool}.{self.view}"
        return [
            items.NoteItem(f"no {self.view} file for {tool} yet", theme.WARN),
            items.NoteItem(""),
            items.NoteItem(f"  howto new {tool} --{self.view}", theme.KEY),
            items.NoteItem(""),
            items.NoteItem("  copies a commented template into", theme.DIM),
            items.NoteItem(f"  {target}", theme.DIM),
            items.NoteItem("  and never overwrites an existing file", theme.DIM),
        ]

    def build_rows(self, loaded):
        width = max(
            self.lay.content_min_width,
            self.right.width - self.lay.key_col - self.lay.frame_rows,
        )
        out, seen = [], set()
        for group in loaded.groups:
            reading = self.reading(loaded, group.probe_kind)
            if reading is not None and reading.error and reading.error not in seen:
                seen.add(reading.error)
                out.append(items.NoteItem(f"! {reading.error}", theme.WARN))
            if group.title:
                out.append(ui.Header(group.title, blank_before=bool(out)))
            for row in group.rows:
                out.append(self.row_item(loaded, row, reading, width))
                key = self.node_key(loaded, row)
                if key in self.open and key in self.kids:
                    out.extend(self.child_items(row, self.kids[key], width))
            if reading is not None and group.probe_kind == "help" and not group.rows:
                key = (loaded.name, loaded.view, 0, loaded.name)
                if key not in self.kids:
                    self.kids[key] = tuple(reading.children(loaded.name))
                out.extend(self.probed_items(self.kids[key], width))
        return out or [items.NoteItem("this file has no rows")]

    def row_item(self, loaded, row, reading, width):
        if not row.is_action:
            keytext, resolved = row.token, True
        else:
            got = reading.resolve(row.token, self.lay.key_col) if reading else None
            keytext, resolved = (got, True) if got else ("unbound", False)
        desc = row.desc or (reading.body(row.token) if reading else "")
        prefix = "  " * row.depth
        if row.expandable:
            prefix += "v " if self.node_key(loaded, row) in self.open else "+ "
        return items.RowItem(row, prefix + keytext, resolved, ui.wrap(desc, width))

    def child_items(self, parent, children, width):
        out = []
        for token, desc, depth in children:
            if depth < 0:
                out.append(ui.Header(token, blank_before=True))
                continue
            child = doc.Row(token, desc, parent.depth + 1, "", 0, False)
            keytext = "  " * child.depth + token
            out.append(items.RowItem(child, keytext, True, ui.wrap(desc, width)))
        return out

    def probed_items(self, children, width):
        out = []
        for token, desc, depth in children:
            if depth < 0:
                continue
            row = doc.Row(token, desc, 0, "", 0, False)
            out.append(items.RowItem(row, token, True, ui.wrap(desc, width)))
        return out

    def open_node(self):
        item = self.right.current()
        tool = self.current_tool()
        loaded = self.get_doc(tool.name, self.view) if tool else None
        if not isinstance(item, items.RowItem) or not loaded or not item.row.expandable:
            return False
        key = self.node_key(loaded, item.row)
        if key in self.open:
            return False
        if key not in self.kids:
            reading = self.reading(loaded, item.row.probe_kind)
            self.kids[key] = tuple(reading.children(item.row.token) if reading else ())
        self.open.add(key)
        identity = self.row_identity(item)
        self.refresh_right()
        self.restore_right_cursor(identity)
        count = sum(1 for child in self.kids[key] if child[2] >= 0)
        self.status = f"{item.row.token}: {count} rows"
        return True

    def close_node(self):
        item = self.right.current()
        tool = self.current_tool()
        loaded = self.get_doc(tool.name, self.view) if tool else None
        if not isinstance(item, items.RowItem) or not loaded or not item.row.expandable:
            return False
        key = self.node_key(loaded, item.row)
        if key not in self.open:
            return False
        self.open.remove(key)
        identity = self.row_identity(item)
        self.refresh_right()
        self.restore_right_cursor(identity)
        return True

    # ----------------------------------------------------------------- scan

    def run_scan(self):
        started = time.perf_counter()
        self.found = scan.scan(settings.DATA, self.known)
        rows = [items.ScanItem(found) for found in self.found]
        self.scanpane.set_items(rows or [items.NoteItem("nothing found that is not described")])
        elapsed = (time.perf_counter() - started) * 1000
        new = sum(1 for found in self.found if found.state == scan.NEW)
        actionable = sum(1 for found in self.found if found.writable)
        self.status = (
            f"scanned in {elapsed:.0f} ms — {new} new, {len(self.found)} rows"
            + ("; nothing to write" if not actionable else "")
        )

    def actions_for(self, found):
        key = (found.tool, found.view)
        if key not in self.scan_actions:
            self.scan_actions[key] = scan.actions_of(self.session, found, self.lay)
        return self.scan_actions[key]

    def scan_write(self):
        targets = [
            item for item in self.scanpane.rows
            if isinstance(item, items.ScanItem) and item.marked
        ]
        if not targets:
            current = self.scanpane.current()
            targets = [current] if isinstance(current, items.ScanItem) else []
        candidates = [item for item in targets if item.found.writable]
        try:
            stubs = [(item.found, self.actions_for(item.found)) for item in candidates]
        except Exception as exc:
            self.status = f"could not prepare stub: {exc}"
            return
        written = []
        for found, actions in stubs:
            try:
                written.append(scan.write_stub(found, actions))
            except OSError as exc:
                self.status = f"could not write: {exc}"
                return
        if not written:
            self.status = "nothing to write here"
            return
        self.docs.clear()
        self.reload()
        self.run_scan()
        self.status = f"wrote {written[0]}" if len(written) == 1 else f"wrote {len(written)} files"

    # --------------------------------------------------------------- drawing

    def draw(self, scr):
        scr.erase()
        height, width = scr.getmaxyx()
        if height < self.lay.terminal_min_height or width < self.lay.terminal_min_width:
            ui.put(scr, 0, 0, "window too small", curses.A_BOLD)
            scr.refresh()
            return
        left_width = self.lay.sidebar_width(width)
        hotkey_height = self.lay.hotkey_height(height) if self.full_footer else 1
        hotkey_top = height - hotkey_height
        pane_height = hotkey_top
        self.left.width, self.left.height = left_width, pane_height
        self.right.width = width - left_width - self.lay.pane_gap
        self.right.height = pane_height
        self.scanpane.width, self.scanpane.height = left_width, pane_height
        self.draw_tabs(scr)
        if self.mode == "scan":
            self.draw_scan(scr, height, left_width)
        else:
            self.draw_list(scr, height, left_width)
            self.draw_content(scr, height, width, left_width)
        for y in range(2, hotkey_top):
            ui.put(scr, y, left_width, "│", curses.color_pair(theme.BORDER))
        if self.full_footer:
            self.draw_hotkeys(scr, height, width)
        else:
            self.draw_compact_footer(scr, height, width)
        if self.overlay:
            self.draw_overlay(scr, height, width)
        scr.refresh()

    def draw_tabs(self, scr):
        ui.put(scr, 0, 1, "howto", curses.color_pair(theme.BAR) | curses.A_BOLD)
        tool = self.current_tool()
        x = 9
        for name, label in (("keys", "KEYS"), ("help", "HELP"), ("scan", "SCAN")):
            if name == "scan":
                active, dim = self.mode == "scan", False
            else:
                active = self.mode == "view" and self.view == name
                dim = self.mode == "scan" or (tool is not None and name not in tool.views)
            if active:
                attr = curses.color_pair(theme.TAB) | curses.A_BOLD | curses.A_REVERSE
            else:
                attr = curses.color_pair(theme.DIM if dim else theme.TAB)
            ui.put(scr, 0, x, f" {label} ", attr)
            x += len(label) + 3

    def draw_list(self, scr, height, left_width):
        focused = self.focus == "left"
        y = 2
        if ui.search_bar_visible(self.left, focused):
            self.draw_search(scr, y, 1, left_width - 2, self.left)
            y += 1
        self.left.follow_cursor(self.left.height - y)
        start, visible = self.left.visible(self.left.height - y)
        for offset, item in enumerate(visible):
            index = start + offset
            if isinstance(item, ui.Divider):
                ui.put(scr, y, 1, "─" * (left_width - 3), curses.color_pair(theme.DIM))
                y += item.required_height()
                continue
            here = index == self.left.cursor
            shown = item.name == self.active_tool
            bar = "▌" if here and focused else ("│" if shown else " ")
            label = f"{bar}{'★' if item.fav else ' '}{'*' if item.present else '-'} {item.name}"
            attr = curses.color_pair(theme.SEL) | curses.A_BOLD if here else 0
            if not here and not item.present:
                attr = curses.color_pair(theme.DIM)
            ui.put(scr, y, 0, label.ljust(left_width - 3)[: left_width - 3], attr)
            ui.put(scr, y, left_width - 3, item.marks(), curses.color_pair(theme.DIM))
            y += 1

    def draw_content(self, scr, height, width, left_width):
        x = left_width + 2
        focused = self.focus == "right"
        tool = self.current_tool()
        if tool is None:
            return
        y = 2
        loaded = self.get_doc(tool.name, self.view)
        if loaded is not None:
            ui.put(scr, y, x, loaded.name, curses.color_pair(theme.KEY) | curses.A_BOLD)
            note = doc.shadow_note(settings.DATA, tool.name, self.view, loaded.layer)
            reading = self.active_reading(loaded)
            if reading is not None and reading.probed_at:
                note += f"  ·  probed {int(time.time() - reading.probed_at)}s ago"
            ui.put(scr, y, x + len(loaded.name) + 2, note, curses.color_pair(theme.DIM))
            y += 1
            if loaded.meta.get("what"):
                ui.put(scr, y, x, loaded.meta["what"], curses.color_pair(theme.DIM))
                y += 1
            if not loaded.present:
                note = loaded.meta.get("install") or "not installed here"
                ui.put(scr, y, x, f"not installed here — {note}", curses.color_pair(theme.WARN))
                y += 1
        y += 1
        if ui.search_bar_visible(self.right, focused):
            self.draw_search(scr, y, x, width - x - 2, self.right)
            y += 1
        self.draw_rows(scr, y, x, self.right.height - y, focused)

    def active_reading(self, loaded):
        for group in loaded.groups:
            if group.probe_kind:
                return self.reading(loaded, group.probe_kind)
        return None

    def draw_rows(self, scr, top, x, height, focused):
        self.right.follow_cursor(height)
        start, visible = self.right.visible(height)
        y = top
        for offset, item in enumerate(visible):
            index = start + offset
            if isinstance(item, ui.Header):
                if item.blank_before:
                    y += 1
                ui.put(scr, y, x, item.title.upper(), curses.color_pair(theme.GROUP) | curses.A_BOLD)
                y += 1
                continue
            if isinstance(item, items.NoteItem):
                ui.put(scr, y, x, item.text, curses.color_pair(item.pair))
                y += 1
                continue
            here = index == self.right.cursor
            attr = curses.color_pair(theme.SEL) | curses.A_BOLD if here and focused else 0
            key_attr = curses.color_pair(theme.DIM) if not item.resolved else (
                attr or curses.color_pair(theme.KEY)
            )
            ui.put(scr, y, x, "▌" if here and focused else " ", attr)
            ui.put(scr, y, x + 1, item.keytext[: self.lay.key_col].ljust(self.lay.key_col), key_attr)
            for line_no, line in enumerate(item.lines):
                line_attr = attr if line_no == 0 else curses.color_pair(theme.DIM)
                ui.put(scr, y + line_no, x + self.lay.key_col + 2, line, line_attr)
            y += item.required_height()

    def draw_scan(self, scr, height, left_width):
        y = 2
        if ui.search_bar_visible(self.scanpane, True):
            self.draw_search(scr, y, 1, left_width - 2, self.scanpane)
            y += 1
        self.scanpane.follow_cursor(self.scanpane.height - y)
        start, visible = self.scanpane.visible(self.scanpane.height - y)
        pairs = {
            scan.NEW: theme.OK, scan.STALE: theme.WARN,
            scan.SHADOWED: theme.KEY, scan.COVERED: theme.DIM,
        }
        state_width = max((len(state) for state in pairs), default=0)
        for offset, item in enumerate(visible):
            index = start + offset
            if isinstance(item, items.NoteItem):
                ui.put(scr, y, 1, item.text, curses.color_pair(theme.DIM))
                y += 1
                continue
            here = index == self.scanpane.cursor and item.can_focus()
            box = "x" if item.marked else " "
            attr = curses.color_pair(theme.SEL) | curses.A_BOLD if here else 0
            if item.found.state == scan.COVERED:
                attr = curses.color_pair(theme.DIM)
            label_width = left_width - state_width
            head = f"{'▌' if here else ' '}[{box}] {item.found.tool}"
            ui.put(scr, y, 0, head.ljust(label_width)[:label_width], attr)
            ui.put(scr, y, label_width, item.found.state, curses.color_pair(pairs[item.found.state]))
            y += 1
        self.draw_stub_preview(scr, self.scanpane.height, left_width + 2)

    def draw_stub_preview(self, scr, height, x):
        current = self.scanpane.current()
        if not isinstance(current, items.ScanItem):
            ui.put(scr, 2, x, "nothing selected", curses.color_pair(theme.DIM))
            return
        found = current.found
        ui.put(scr, 2, x, f"{found.tool}.{found.view}", curses.color_pair(theme.KEY) | curses.A_BOLD)
        source = found.conf if found.conf else "the tool itself"
        ui.put(scr, 3, x, f"probe {found.probe_kind}  ·  read from {source}", curses.color_pair(theme.DIM))
        ui.put(scr, 4, x, f"would write {found.target}", curses.color_pair(theme.DIM))
        y = 7
        if found.state == scan.SHADOWED:
            ui.put(scr, 6, x, f"your own {found.tool}.{found.view} still wins after this",
                   curses.color_pair(theme.WARN))
            y += 1
        for line in scan.stub_text(found, self.actions_for(found)).splitlines():
            if y >= height - 1:
                ui.put(scr, y - 1, x, "…", curses.color_pair(theme.DIM))
                break
            pair = theme.DIM if line.startswith("#") else (
                theme.GROUP if line.startswith("=") else 0
            )
            ui.put(scr, y, x, line, curses.color_pair(pair) if pair else 0)
            y += 1

    def draw_search(self, scr, y, x, width, pane):
        if pane.searching:
            text = f"/{pane.query}▌"
            attr = curses.color_pair(theme.BAR)
        else:
            count = sum(1 for item in pane.rows if item.can_focus())
            text = f"/{pane.query}  ({count})"
            attr = curses.color_pair(theme.DIM)
        ui.put(scr, y, x, text.ljust(width), attr)

    def draw_hotkeys(self, scr, height, width):
        """One resize-safe, paged grid at the bottom."""
        panel_height = self.lay.hotkey_height(height)
        top = height - panel_height
        bottom = height - 1
        rows = self.km.footer_rows().get(self.mode, ())
        panel_width = width - 1
        body_height = max(0, panel_height - 2)
        notice = self.status
        notice_rows = 1 if notice and body_height > 1 else 0
        body_height -= notice_rows
        cells, self.hotkey_at, self.hotkey_page, cell_width = layout.hotkey_grid(
            rows, max(0, panel_width - 4), body_height, self.hotkey_at
        )
        if not rows or panel_width < 8 or bottom <= top:
            return
        border = curses.color_pair(theme.BORDER)
        last = min(len(rows), self.hotkey_at + self.hotkey_page)
        shown = f"{self.hotkey_at + 1}–{last} of {len(rows)}"
        label = f" Hotkeys  {shown} "
        fill = max(0, panel_width - len(label) - 2)
        ui.put(scr, top, 0, "╭" + label + "─" * fill + "╮", border)
        if notice:
            ui.put(scr, top + 1, 2, notice[: max(0, panel_width - 4)], curses.color_pair(theme.BAR))
        row_top = top + 1 + notice_rows
        for y in range(top + 1, bottom):
            ui.put(scr, y, 0, "│", border)
            ui.put(scr, y, panel_width - 1, "│", border)
        ui.put(scr, bottom, 0, "╰" + "─" * (panel_width - 2) + "╯", border)
        for row_no, column, (key, desc) in cells:
            x = 2 + column * cell_width
            available = max(1, min(cell_width - 1, panel_width - x - 1))
            key_width = min(len(key), max(1, available // 2))
            ui.put(scr, row_top + row_no, x, key[:key_width], curses.color_pair(theme.KEY))
            desc_x = x + key_width + 1
            ui.put(scr, row_top + row_no, desc_x, desc[: max(0, available - key_width - 1)])

    def draw_compact_footer(self, scr, height, width):
        rows = self.km.compact_footer_rows().get(self.mode, ())
        bar = " " + "   ".join(f"{key} {label}" for key, label in rows) + " "
        ui.put(scr, height - 1, 0, bar.ljust(width - 1)[: width - 1], curses.color_pair(theme.BAR))

    def overlay_rows(self):
        rows, last = [], None
        for section, spec, desc, _ in self.km.rows():
            if section != last:
                rows.append(("head", section.upper(), ""))
                last = section
            rows.append(("row", spec, desc))
        if self.errors:
            rows.append(("head", "ERRORS", ""))
            for error in self.errors:
                lines = ui.wrap(error, max(4, self.lay.overlay_max_width - 6))
                rows.extend(("row", "!" if index == 0 else "", line)
                            for index, line in enumerate(lines))
        return rows

    def draw_overlay(self, scr, height, width):
        rows = self.overlay_rows()
        box_width = min(width - self.lay.overlay_margin, self.lay.overlay_max_width)
        box_height = min(
            height - self.lay.overlay_vertical_margin,
            len(rows) + self.lay.overlay_frame_rows,
        )
        body = box_height - self.lay.overlay_frame_rows
        self.overlay_at = max(0, min(self.overlay_at, max(0, len(rows) - body)))
        y0, x0 = (height - box_height) // 2, (width - box_width) // 2
        for y in range(y0, y0 + box_height):
            ui.put(scr, y, x0, " " * box_width, curses.color_pair(theme.BAR))
        body_rows = rows[self.overlay_at : self.overlay_at + body]
        key_width = max((len(first) for kind, first, _ in rows if kind == "row"), default=0)
        for offset, (kind, first, second) in enumerate(body_rows):
            y = y0 + 1 + offset
            if kind == "head":
                ui.put(scr, y, x0 + 2, first, curses.color_pair(theme.GROUP) | curses.A_BOLD)
            else:
                ui.put(scr, y, x0 + 3, first.ljust(key_width), curses.color_pair(theme.KEY))
                ui.put(scr, y, x0 + key_width + 4, second)
        shown = f"{self.overlay_at + 1}-{self.overlay_at + min(body, len(rows))} of {len(rows)}"
        footer = f"  {shown}   up/down scroll   any other key closes"
        ui.put(scr, y0 + box_height - 2, x0 + 1, footer[: box_width - 2], curses.color_pair(theme.DIM))

    # ---------------------------------------------------------------- input

    def pane(self):
        if self.mode == "scan":
            return self.scanpane
        return self.left if self.focus == "left" else self.right

    def key(self, ch, scr):
        height, _ = scr.getmaxyx()
        page = max(1, height - 8)
        pane = self.pane()
        if pane.searching:
            return self.search_key(ch, pane)
        if self.overlay:
            return self.overlay_key(ch, height)
        action = self.dispatch.get(ch)
        if action is None:
            return True
        self.status = ""
        return self.act(action, pane, page)

    def overlay_key(self, ch, height):
        action = self.dispatch.get(ch)
        step = {
            "down": 1, "up": -1, "page_down": height, "page_up": -height,
        }.get(action)
        if step is None:
            self.overlay = False
            self.overlay_at = 0
        else:
            self.overlay_at = max(0, self.overlay_at + step)
        return True

    def search_key(self, ch, pane):
        named = keymap.named()
        rebuild = False
        if ch in named["esc"]:
            pane.searching = False
            pane.apply_filter("")
            rebuild = True
        elif ch in named["enter"]:
            pane.searching = False
        elif ch in named["backspace"]:
            pane.apply_filter(pane.query[:-1])
            rebuild = True
        elif 32 <= ch < 127:
            pane.apply_filter(pane.query + chr(ch))
            rebuild = True
        if self.mode == "view" and pane is self.left:
            self.refresh_right()
        elif self.mode == "view" and pane is self.right:
            tool = self.current_tool()
            loaded = self.get_doc(tool.name, self.view) if tool else None
            if loaded is not None:
                if rebuild:
                    query = pane.query
                    self.apply_right_filter(loaded, query)
        return True

    def act(self, action, pane, page):
        if action == "quit":
            return False
        if action == "help":
            self.overlay = True
            self.overlay_at = 0
        elif action == "search":
            if self.mode == "view" and pane is self.right:
                self.open_resolved_nodes()
            pane.searching = True
            if self.mode == "view" and pane is self.right:
                tool = self.current_tool()
                loaded = self.get_doc(tool.name, self.view) if tool else None
                if loaded is not None:
                    self.apply_right_filter(loaded, "")
            else:
                pane.apply_filter("")
        elif action == "down":
            pane.move(1)
            self.after_move(pane)
        elif action == "up":
            pane.move(-1)
            self.after_move(pane)
        elif action == "page_down":
            pane.scroll_by(page)
            self.after_move(pane)
        elif action == "page_up":
            pane.scroll_by(-page)
            self.after_move(pane)
        elif action == "home":
            pane.to_edge(False)
            self.after_move(pane)
        elif action == "end":
            pane.to_edge(True)
            self.after_move(pane)
        elif action in ("view_keys", "view_help"):
            self.mode = "view"
            self.view = "keys" if action == "view_keys" else "help"
            self.refresh_right()
        elif action == "view_scan":
            self.mode = "scan"
            self.focus = "left"
            self.run_scan()
        elif action == "next_pane":
            self.focus = "right" if self.focus == "left" else "left"
        elif action == "prev_pane":
            self.focus = "left" if self.focus == "right" else "right"
        elif action == "focus_list":
            self.focus = "left"
        elif action == "confirm":
            if self.mode == "scan":
                self.scan_write()
            elif self.focus == "left":
                self.focus = "right"
            else:
                self.open_node()
        elif action == "back":
            if self.mode == "scan":
                self.mode = "view"
            elif self.focus == "right" and not self.close_node():
                self.focus = "left"
        elif action == "favorite":
            self.toggle_favorite()
        elif action in ("refresh", "refresh_all"):
            self.refresh(action == "refresh_all")
        elif action == "hotkeys_next":
            self.hotkey_at += self.hotkey_page
        elif action == "hotkeys_prev":
            self.hotkey_at = max(0, self.hotkey_at - self.hotkey_page)
        elif action == "footer_view":
            self.full_footer = not self.full_footer
            self.hotkey_at = 0
        elif action == "scan_select_mode" and self.mode == "scan":
            self.select_mode = not self.select_mode
            self.status = f"select mode {'on' if self.select_mode else 'off'}"
        elif action == "scan_extend" and self.mode == "scan":
            self.mark_current()
        elif action == "scan_mark_all" and self.mode == "scan":
            count = 0
            for item in self.scanpane.rows:
                if isinstance(item, items.ScanItem) and item.found.state == scan.NEW:
                    item.marked = True
                    count += 1
            self.status = f"marked {count} NEW row(s)"
        return True

    def after_move(self, pane):
        if self.mode == "view" and pane is self.left:
            self.refresh_right()

    def mark_current(self):
        item = self.scanpane.current()
        if isinstance(item, items.ScanItem) and item.found.writable:
            item.marked = not item.marked
        self.scanpane.move(1)

    def toggle_favorite(self):
        tool = self.current_tool()
        if tool is None:
            return
        self.favs, saved = favorites.toggle(self.favs, tool.name)
        if not saved:
            self.status = f"could not write {favorites.path()}"
            return
        name = tool.name
        self.reload()
        self.status = f"{name} {'pinned' if name in self.favs else 'unpinned'}"

    def refresh(self, everything):
        if everything:
            self.session.invalidate()
            self.docs.clear()
            self.open.clear()
            self.kids.clear()
            self.scan_actions.clear()
            self.reload()
            if self.mode == "scan":
                self.run_scan()
            self.status = "re-probed everything"
            return
        if self.mode == "scan":
            current = self.scanpane.current()
            if isinstance(current, items.ScanItem):
                self.session.invalidate(current.found.tool)
                self.scan_actions = {
                    key: actions for key, actions in self.scan_actions.items()
                    if key[0] != current.found.tool
                }
            self.run_scan()
            return
        tool = self.current_tool()
        if tool is None:
            return
        self.session.invalidate(tool.name)
        self.docs = {key: value for key, value in self.docs.items() if key[0] != tool.name}
        self.open = {key for key in self.open if key[0] != tool.name}
        self.kids = {key: value for key, value in self.kids.items() if key[0] != tool.name}
        self.scan_actions = {
            key: actions for key, actions in self.scan_actions.items() if key[0] != tool.name
        }
        self.refresh_right()
        self.status = f"re-probed {tool.name}.{self.view}"

    def open_resolved_nodes(self):
        tool = self.current_tool()
        loaded = self.get_doc(tool.name, self.view) if tool else None
        if loaded is None:
            return
        self.open |= {key for key in self.kids if key[:2] == (loaded.name, loaded.view)}
        self.refresh_right()


def main(scr):
    curses.curs_set(0)
    spec, theme_errors = theme.load()
    if theme.apply(curses, spec):
        scr.bkgd(" ", curses.color_pair(theme.TEXT))
    keymap.bind(curses)
    scr.keypad(True)
    app = App(startup_errors=theme_errors)
    while True:
        app.draw(scr)
        ch = scr.getch()
        if ch == curses.KEY_RESIZE:
            continue
        if not app.key(ch, scr):
            return
