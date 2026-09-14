"""Plain-text commands that do not require curses."""

from . import doc, host, layout, probes, scan, settings


def cmd_list(argv):
    catalog = doc.catalog(settings.DATA)
    if not catalog:
        print(f"no *.keys or *.help files in {[str(path) for _, path in doc.layers(settings.DATA)]}")
        return 1
    lay, errors = layout.load()
    for error in errors:
        print(f"! {error}")
    session = probes.Session()
    for tool in sorted(catalog):
        for view in doc.VIEWS:
            entry = catalog[tool].get(view)
            if not entry:
                continue
            layer_name, path = entry
            loaded = doc.load(path, layer_name)
            flag = "" if loaded.present else "  (not installed here)"
            print(f"\n## {tool}.{view}{flag} — {loaded.meta.get('what', '')}  [{layer_name}]")
            for error in loaded.errors:
                print(f"! {error}")
            readings = {}
            for group in loaded.groups:
                reading = readings.get(group.probe_kind)
                if group.probe_kind not in readings:
                    reading = session.read(
                        group.probe_kind, probes.Ctx.of(loaded, lay.probe_timeout)
                    ) if group.probe_kind else None
                    readings[group.probe_kind] = reading
                print(f"\n  {group.title}")
                if reading and reading.error:
                    print(f"    ! {reading.error}")
                for row in group.rows:
                    key = row.token
                    if row.is_action:
                        key = (reading.resolve(row.token, lay.key_col) if reading else None) or "unbound"
                    print(f"    {'  ' * row.depth}{key:<{lay.key_col}} {row.desc}")
                if reading and group.probe_kind == "help" and not group.rows:
                    for token, desc, depth in reading.children(loaded.name):
                        if depth >= 0:
                            print(f"    {token:<{lay.key_col}} {desc}")
    return 0


def cmd_where(args):
    if not args:
        print("usage: howto where <tool>")
        return 2
    tool, found = args[0], False
    for view in doc.VIEWS:
        stack = doc.find(settings.DATA, tool, view)
        if not stack:
            continue
        found = True
        print(f"{tool}.{view}")
        for index, (layer_name, path) in enumerate(stack):
            print(f"  {'WINS  ' if index == 0 else 'shadow'}  {layer_name:<10} {path}")
    if not found:
        print(f"no file for {tool} in any layer")
        return 1
    return 0


def requested_views(args):
    return [view for view in doc.VIEWS if f"--{view}" in args]


def cmd_new(args):
    views = requested_views(args)
    names = [arg for arg in args if not arg.startswith("-")]
    if not names or not views:
        print("usage: howto new <tool> --keys|--help")
        return 2
    tool = names[0]
    for view in views:
        source = settings.TEMPLATES / f"tool.{view}"
        target = host.config_dir() / f"{tool}.{view}"
        if not source.is_file():
            print(f"no template at {source}")
            return 1
        if target.exists():
            print(f"refusing to overwrite {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8") as output:
                output.write(source.read_text(encoding="utf-8").replace("{{TOOL}}", tool))
        except FileExistsError:
            print(f"refusing to overwrite {target}")
            continue
        print(f"wrote {target}")
    return 0


def cmd_edit(args):
    views = requested_views(args)
    names = [arg for arg in args if not arg.startswith("-")]
    if not names:
        print("usage: howto edit <tool> [--keys|--help]")
        return 2
    tool = names[0]
    for view in views or doc.VIEWS:
        stack = doc.find(settings.DATA, tool, view)
        if not stack:
            continue
        layer_name, path = stack[0]
        target = host.config_dir() / f"{tool}.{view}"
        if layer_name != "yours":
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("x", encoding="utf-8") as output:
                    output.write(path.read_text(encoding="utf-8"))
            except FileExistsError:
                print(f"refusing to overwrite {target}")
                return 1
            print(f"promoted {layer_name} -> {target}")
        return host.open_editor(target)
    print(f"no file for {tool} in any layer — try: howto new {tool} --keys")
    return 1


def cmd_scan(args):
    known, errors = scan.load_known()
    for error in errors:
        print(f"! {error}")
    found = scan.scan(settings.DATA, known)
    lay, layout_errors = layout.load()
    for error in layout_errors:
        print(f"! {error}")
    session = probes.Session()
    for item in found:
        target = f"{item.tool}.{item.view}"
        print(f"{item.state:<9} {target:<16} probe={item.probe_kind:<13} -> {item.target}")
    todo = [item for item in found if item.state in (scan.NEW, scan.STALE)]
    write = "--write" in args
    unknown = [arg for arg in args if arg not in ("--write", "--dry-run")]
    if unknown or (args and not write and "--dry-run" not in args):
        print("usage: howto scan --dry-run|--write")
        return 2
    if write:
        for item in todo:
            actions = scan.actions_of(session, item, lay)
            try:
                print(f"wrote {scan.write_stub(item, actions)}")
            except FileExistsError:
                print(f"refusing to overwrite {item.target}")
                return 1
        return 0
    print(f"\n{len(found)} found, {len(todo)} would be written. Nothing written.")
    print("Open the SCAN tab (run `howto`, press its configured key) to write one at a time.")
    return 0


def cmd_config(args):
    for name in settings.NAMES:
        source = settings.shipped_path(name)
        target = settings.user_path(name)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as output:
                output.write(source.read_text(encoding="utf-8"))
            print(f"wrote {target}")
        except FileExistsError:
            print(f"skipped {target} — already exists")
            continue
        except OSError as exc:
            print(f"could not write {target}: {exc}")
            return 1
    return 0


USAGE = """howto — the keys and the commands for the tools on this machine

  howto                     the browser; its full live keymap stays at the bottom
  howto --list              every row as plain text, for grepping
  howto where <tool>        which layer wins, and what it shadows
  howto new <tool> --keys   copy a template into your own config dir
  howto edit <tool>         promote the winning file to yours, then $EDITOR
  howto scan --dry-run      what a scan would propose, writing nothing
  howto scan --write        write NEW and STALE generated stubs
  howto config              copy the four configurable TOMLs, never overwriting
"""


def cli(argv):
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if "--list" in argv:
        return cmd_list(argv)
    if not argv:
        return None
    command, rest = argv[0], argv[1:]
    commands = {
        "where": cmd_where, "new": cmd_new, "edit": cmd_edit,
        "scan": cmd_scan, "config": cmd_config,
    }
    if command in commands:
        return commands[command](rest)
    print(USAGE)
    return 2
