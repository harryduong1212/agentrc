"""superfile's hotkeys.toml: `action = [keys]` at the top level, not nested
under a table — a first pass that looked for tables found 0 of 46."""

from . import Kind, Result


def read(ctx):
    if not ctx.conf or not ctx.conf.is_file():
        return Result.of(error=f"no config at {ctx.conf}")
    try:
        import tomllib
    except ImportError:  # < 3.11
        try:
            import tomli as tomllib
        except ImportError:
            return Result.of(error="no TOML reader — python 3.11+, or pip install tomli")
    with ctx.conf.open("rb") as fh:
        d = tomllib.load(fh)
    # The file pads short lists with "" to keep two columns. Those are not
    # bindings, and rendering them gives you "Q, " with a trailing comma.
    table = {
        k: [str(x) for x in v if str(x).strip()]
        for k, v in d.items()
        if isinstance(v, list)
    }
    return Result.of(table)


KIND = Kind("toml-actions", read)
