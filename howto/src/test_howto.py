import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from howto import app, cli, doc, favorites, items, keymap, layout, probes, scan, settings, theme, ui
from howto.probes import helpcmd, kdl, tmux, yaml_keys


class KeymapTests(unittest.TestCase):
    def setUp(self):
        fake = mock.Mock()
        names = {
            "KEY_ENTER": 343, "KEY_BACKSPACE": 263, "KEY_UP": 259,
            "KEY_DOWN": 258, "KEY_LEFT": 260, "KEY_RIGHT": 261,
            "KEY_PPAGE": 339, "KEY_NPAGE": 338, "KEY_HOME": 262,
            "KEY_END": 360, "KEY_SLEFT": 393, "KEY_SRIGHT": 402,
            "KEY_SR": 337, "KEY_SF": 336,
        }
        for name, value in names.items():
            setattr(fake, name, value)
        for number in range(1, 13):
            setattr(fake, f"KEY_F{number}", 1000 + number)
        keymap._NAMED = {}
        keymap.bind(fake)

    def test_shipped_config_has_one_source_for_keys(self):
        km = keymap.load()
        dispatch = km.dispatch()
        overlay = {code for entry in km.entries for code in keymap.codes(entry.keys)}
        self.assertFalse(km.errors)
        self.assertEqual(overlay, set(dispatch))
        for _, rows in km.footer:
            for action, _ in rows:
                self.assertIn(action, dispatch.values())

    def test_build_reports_drift(self):
        km = keymap.build({
            "keys": {"shown": ["x"], "hidden": ["y"], "empty": []},
            "overlay": {"one": ["shown", "empty"], "two": ["shown"]},
            "footer": {"view": ["missing", "empty"]},
        })
        joined = "\n".join(km.errors)
        self.assertIn("hidden", joined)
        self.assertIn("more than one section", joined)
        self.assertIn("[overlay] lists 'empty'", joined)
        self.assertIn("[footer.view] lists 'missing'", joined)
        self.assertIn("[footer.view] lists 'empty'", joined)

    def test_build_reports_unknown_key_name(self):
        km = keymap.build({
            "keys": {"action": ["not-a-terminal-key"]},
            "overlay": {"one": ["action"]},
        })
        self.assertIn("unknown key", "\n".join(km.errors))

    def test_build_reports_duplicate_binding(self):
        km = keymap.build({
            "keys": {"first": ["x"], "second": ["x"]},
            "overlay": {"one": ["first", "second"]},
        })
        self.assertIn("bound to both", "\n".join(km.errors))


class ParserTests(unittest.TestCase):
    def test_nesting_keeps_every_depth(self):
        _, groups, errors = doc.parse_text("= X\na | one\n  b | two\n    c | three\n")
        self.assertFalse(errors)
        self.assertEqual([row.depth for row in groups[0].rows], [0, 1, 2])

    def test_filter_keeps_nested_match_ancestors(self):
        rows = [
            ui.Header("X", False),
            items.RowItem(doc.Row("a", "", 0, "", 1, False), "a", True, [""]),
            items.RowItem(doc.Row("b", "", 1, "", 2, False), "b", True, [""]),
            items.RowItem(doc.Row("needle", "", 2, "", 3, False), "needle", True, [""]),
            items.RowItem(doc.Row("sibling", "", 2, "", 4, False), "sibling", True, [""]),
            items.RowItem(doc.Row("other", "", 0, "", 4, False), "other", True, [""]),
        ]
        pane = ui.Pane()
        pane.set_items(rows)
        pane.apply_filter("needle")
        self.assertEqual(
            [getattr(getattr(item, "row", None), "token", "header") for item in pane.rows],
            ["header", "a", "b", "needle"],
        )

    def test_filter_keeps_descendants_of_matching_parent(self):
        rows = [
            ui.Header("X", False),
            items.RowItem(doc.Row("parent", "", 0, "", 1, False), "parent", True, [""]),
            items.RowItem(doc.Row("child", "", 1, "", 2, False), "child", True, [""]),
            items.RowItem(doc.Row("other", "", 0, "", 3, False), "other", True, [""]),
        ]
        pane = ui.Pane()
        pane.set_items(rows)
        pane.apply_filter("parent")
        self.assertEqual(
            [getattr(getattr(item, "row", None), "token", "header") for item in pane.rows],
            ["header", "parent", "child"],
        )

    def test_filter_does_not_repeat_blocks_between_headers(self):
        rows = [
            ui.Header("ONE", False),
            items.RowItem(doc.Row("first", "", 0, "", 1, False), "first", True, [""]),
            ui.Header("TWO"),
            items.RowItem(doc.Row("second", "", 0, "", 2, False), "second", True, [""]),
        ]
        pane = ui.Pane()
        pane.set_items(rows)
        pane.apply_filter("second")
        self.assertEqual(len(pane.rows), 2)
        self.assertEqual(pane.rows[0].title, "TWO")


class SessionTests(unittest.TestCase):
    def test_result_freezes_probe_tables(self):
        result = probes.Result.of({"action": ["key"]}, {"action": "body"})
        self.assertEqual(result.table, (("action", ("key",)),))
        self.assertEqual(result.bodies, (("action", "body"),))

    def test_help_cache_is_per_tool(self):
        session = probes.Session()
        first = session.read("help", probes.Ctx(None, {"name": "git"}, 1))
        second = session.read("help", probes.Ctx(None, {"name": "gh"}, 1))
        self.assertIsNot(first, second)
        self.assertEqual(len(session._memo), 2)

    def test_help_parser_accepts_command_interfaces(self):
        _, commands = helpcmd.parse_help(
            "User-facing repository, command and file interfaces\n"
            "   attributes              Defining attributes per path\n\n"
            "Options:\n   --help                  Show help\n"
        )
        self.assertEqual(commands, [("attributes", "Defining attributes per path")])

    def test_help_parser_reads_flags_from_usage(self):
        flags, _ = helpcmd.parse_help("usage: git [-v | --version] [-C <path>]\n")
        self.assertEqual(flags, [("-v", ""), ("--version", ""), ("-C", "")])

    def test_empty_help_group_shows_live_rows(self):
        row = doc.Group("ALL FLAGS", "help", ())
        loaded = doc.Doc({"name": "demo"}, (row,), Path("demo.help"), "shipped", ())
        instance = app.App.__new__(app.App)
        instance.lay = layout.load()[0]
        instance.right = ui.Pane()
        instance.right.width = 80
        instance.open, instance.kids = set(), {}
        reading = mock.Mock(error="", children=mock.Mock(return_value=[("--live", "now", 0)]))
        with mock.patch.object(instance, "reading", return_value=reading):
            rows = instance.build_rows(loaded)
        self.assertTrue(any(getattr(item, "keytext", "") == "--live" for item in rows))

    def test_tmux_does_not_invent_a_prefix_when_it_cannot_find_one(self):
        rows = [("prefix", "x", ["split-window", "-h"])]
        self.assertEqual(tmux.prefix_key(rows), "")

    def test_kdl_probe_reads_supported_single_line_binding(self):
        self.assertEqual(kdl.parse('bind "Ctrl x" "Alt y" { NewPane; }\n'), {
            "NewPane": ["Ctrl x", "Alt y"],
        })

    def test_yaml_probe_flattens_nested_binding_paths(self):
        self.assertEqual(yaml_keys.flatten_paths({
            "keybinding": {"universal": {"quit": "q", "prev": ["k", "up"]}},
        }), {
            "keybinding.universal.quit": ["q"],
            "keybinding.universal.prev": ["k", "up"],
        })


class LayerTests(unittest.TestCase):
    def test_generated_catalog_becomes_stale_after_source_change(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = root / "config"
            generated = config / "howto" / "generated"
            generated.mkdir(parents=True)
            target = generated / "demo.keys"
            target.write_text("name: demo\n")
            conf = root / "demo.conf"
            conf.write_text("new\n")
            os.utime(conf, (target.stat().st_mtime + 1, target.stat().st_mtime + 1))
            old = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = str(config)
            try:
                have = doc.catalog(root / "empty")
                self.assertEqual(scan.classify("demo", "keys", have, target, conf), scan.STALE)
            finally:
                if old is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old

    def test_new_stub_refuses_an_existing_target(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "demo.keys"
            target.write_text("mine\n")
            found = scan.Found("demo", "keys", scan.NEW, target, "help", None)
            with self.assertRaises(FileExistsError):
                scan.write_stub(found, ())
            self.assertEqual(target.read_text(), "mine\n")

    def test_stale_generated_stub_is_refreshed(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "demo.keys"
            target.write_text("stale\n")
            found = scan.Found("demo", "keys", scan.STALE, target, "help", None)
            scan.write_stub(found, ("demo",))
            self.assertIn("@demo", target.read_text())

    def test_favorites_replace_atomically(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "favorites.json"
            with mock.patch.object(favorites, "path", return_value=target):
                self.assertTrue(favorites.write(("b", "a")))
                self.assertEqual(favorites.read({"a", "b"})[0], ("a", "b"))


class ConfigTests(unittest.TestCase):
    def test_every_shipped_toml_loads(self):
        self.assertFalse(keymap.load().errors)
        self.assertFalse(layout.load()[1])
        self.assertFalse(scan.load_known()[1])
        self.assertFalse(theme.load()[1])
        for name in settings.NAMES:
            _, error = settings.read_toml(settings.shipped_path(name))
            self.assertFalse(error)

    def test_layout_reports_bad_override_and_keeps_shipped_value(self):
        base, _ = settings.read_toml(settings.shipped_path("config"))
        merged = settings.merge(base, {"layout": {"sidebar_ratio": "wide"}})
        with mock.patch.object(settings, "load", return_value=(merged, ())):
            value, errors = layout.load()
        self.assertTrue(errors)
        self.assertEqual(value.sidebar_ratio, base["layout"]["sidebar_ratio"])

    def test_theme_reports_bad_color(self):
        base, _ = settings.read_toml(settings.shipped_path("theme"))
        merged = settings.merge(base, {"colors": {"key": "not-a-color"}})
        with mock.patch.object(settings, "load", return_value=(merged, ())):
            _, errors = theme.load()
        self.assertTrue(errors)

    def test_settings_reports_unknown_user_table(self):
        with tempfile.TemporaryDirectory() as raw:
            old = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = raw
            target = Path(raw) / "howto" / "theme.toml"
            target.parent.mkdir()
            target.write_text("[colours]\nkey = 'red'\n")
            try:
                _, errors = settings.load("theme")
            finally:
                if old is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old
        self.assertIn("unknown top-level table", "\n".join(errors))

    def test_config_command_copies_once_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shipped = root / "shipped"
            yours = root / "yours"
            shipped.mkdir()
            source = shipped / "theme.toml"
            source.write_text("value = 'shipped'\n")
            with (
                mock.patch.object(settings, "NAMES", ("theme",)),
                mock.patch.object(settings, "shipped_path", side_effect=lambda name: shipped / f"{name}.toml"),
                mock.patch.object(settings, "user_path", side_effect=lambda name: yours / f"{name}.toml"),
            ):
                self.assertEqual(cli.cmd_config([]), 0)
                target = yours / "theme.toml"
                self.assertEqual(target.read_text(), "value = 'shipped'\n")
                target.write_text("value = 'mine'\n")
                self.assertEqual(cli.cmd_config([]), 0)
                self.assertEqual(target.read_text(), "value = 'mine'\n")


if __name__ == "__main__":
    unittest.main()
