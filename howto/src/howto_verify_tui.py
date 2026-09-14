import curses
import os
import traceback
from pathlib import Path

from howto import app, items, keymap, theme


OUT = Path(os.environ["HOWTO_VERIFY_OUT"])


def run(scr):
    spec, errors = theme.load()
    theme.apply(curses, spec)
    keymap.bind(curses)
    instance = app.App(errors)
    screens = 0
    for view in ("keys", "help"):
        instance.view = view
        for index, item in enumerate(instance.left.rows):
            if not item.can_focus():
                continue
            instance.left.cursor = index
            instance.refresh_right()
            instance.draw(scr)
            text = "\n".join(
                scr.instr(y, 0).decode("utf-8", "replace")
                for y in range(scr.getmaxyx()[0])
            )
            if "howto" not in text:
                raise AssertionError(f"missing title for {item.name}.{view}")
            screens += 1

    by_name = {
        item.name: index
        for index, item in enumerate(instance.left.rows)
        if isinstance(item, items.ToolItem)
    }

    # An empty ALL FLAGS group must render rows from the live --help probe.
    instance.view = "help"
    instance.left.cursor = by_name["rg"]
    instance.refresh_right()
    if not any(
        isinstance(item, items.RowItem) and "--hidden" in item.keytext
        for item in instance.right.rows
    ):
        raise AssertionError("rg live --help rows did not render")
    instance.draw(scr)

    # Search must keep a matching nested row and the ancestors that explain it.
    instance.left.cursor = by_name["git"]
    instance.refresh_right()
    loaded = instance.get_doc("git", "help")
    instance.apply_right_filter(loaded, "amend no edit")
    tokens = {
        item.row.token
        for item in instance.right.rows
        if isinstance(item, items.RowItem)
    }
    if not {"git commit", "--amend --no-edit"}.issubset(tokens):
        raise AssertionError(f"nested search lost context: {sorted(tokens)}")
    instance.draw(scr)

    # Draw both ends of the live keymap overlay; it is taller than this screen.
    instance.overlay = True
    instance.overlay_at = 0
    instance.draw(scr)
    first_overlay = "\n".join(
        scr.instr(y, 0).decode("utf-8", "replace")
        for y in range(scr.getmaxyx()[0])
    )
    if "PANES" not in first_overlay:
        raise AssertionError("help overlay did not render its first section")
    instance.overlay_at = len(instance.overlay_rows())
    instance.draw(scr)
    last_overlay = "\n".join(
        scr.instr(y, 0).decode("utf-8", "replace")
        for y in range(scr.getmaxyx()[0])
    )
    if "SCAN TAB" not in last_overlay:
        raise AssertionError("help overlay did not scroll to its last section")

    OUT.write_text(
        f"screens {screens}\ntools {len(instance.cat)}\n"
        "live-help ok\nsearch ok\noverlay ok\n"
        f"errors {len(instance.errors)}\n"
    )


try:
    curses.wrapper(run)
except Exception:
    OUT.write_text(traceback.format_exc())
    raise
