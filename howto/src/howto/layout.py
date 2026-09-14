"""The sizes and timeouts, read from `config.toml`.

One record, loaded once, passed where it is needed — so no module reaches for a
global to find out how wide a column is.
"""

from typing import NamedTuple

from . import settings


FIELDS = {
    "layout": (
        "terminal_min_height", "terminal_min_width", "frame_rows", "pane_gap", "content_min_width",
        "overlay_vertical_margin", "sidebar_ratio",
        "sidebar_min", "sidebar_max", "key_col", "overlay_max_width",
        "overlay_margin", "overlay_frame_rows",
    ),
    "probe": ("timeout",),
    "scan": ("help_actions", "key_actions"),
}


class Layout(NamedTuple):
    terminal_min_height: int
    terminal_min_width: int
    frame_rows: int
    pane_gap: int
    overlay_vertical_margin: int
    content_min_width: int
    sidebar_ratio: int
    sidebar_min: int
    sidebar_max: int
    key_col: int
    overlay_max_width: int
    overlay_margin: int
    overlay_frame_rows: int
    probe_timeout: int
    scan_help_actions: int
    scan_key_actions: int

    def sidebar_width(self, term_width):
        return max(self.sidebar_min, min(self.sidebar_max, term_width // self.sidebar_ratio))


def build(data):
    """Pure: merged config in, a Layout out."""
    lay = settings.section(data, "layout")
    probe = settings.section(data, "probe")
    scan = settings.section(data, "scan")
    return Layout(
        terminal_min_height=max(1, settings.as_int(lay, "terminal_min_height")),
        terminal_min_width=max(1, settings.as_int(lay, "terminal_min_width")),
        frame_rows=max(1, settings.as_int(lay, "frame_rows")),
        pane_gap=max(1, settings.as_int(lay, "pane_gap")),
        overlay_vertical_margin=max(1, settings.as_int(lay, "overlay_vertical_margin")),
        content_min_width=max(1, settings.as_int(lay, "content_min_width")),
        sidebar_ratio=max(2, settings.as_int(lay, "sidebar_ratio")),
        sidebar_min=max(8, settings.as_int(lay, "sidebar_min")),
        sidebar_max=max(8, settings.as_int(lay, "sidebar_max")),
        key_col=max(6, settings.as_int(lay, "key_col")),
        overlay_max_width=max(
            20, settings.as_int(lay, "overlay_max_width")
        ),
        overlay_margin=max(1, settings.as_int(lay, "overlay_margin")),
        overlay_frame_rows=max(1, settings.as_int(lay, "overlay_frame_rows")),
        probe_timeout=max(1, settings.as_int(probe, "timeout")),
        scan_help_actions=max(1, settings.as_int(scan, "help_actions")),
        scan_key_actions=max(1, settings.as_int(scan, "key_actions")),
    )


def load():
    data, errors = settings.load("config")
    base, base_error = settings.read_toml(settings.shipped_path("config"))
    more = []
    clean = dict(data)
    for section_name, fields in FIELDS.items():
        values = dict(settings.section(data, section_name))
        defaults = settings.section(base, section_name)
        for key in values:
            if key not in fields:
                more.append(f"config: unknown [{section_name}] key '{key}'")
        for key in fields:
            value = values.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                more.append(f"config: {section_name}.{key} must be an integer")
                values[key] = defaults.get(key)
        clean[section_name] = values
    all_errors = tuple(errors) + tuple(e for e in (base_error,) if e) + tuple(more)
    return build(clean), all_errors
