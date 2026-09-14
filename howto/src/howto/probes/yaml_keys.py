"""lazygit's `config.yml`. If lazygit or its config is absent, this degrades
loudly rather than pretending an empty table is an answer.

PyYAML is not stdlib. Absent is the normal case, not an error: the literal rows
still render and the panel header says why the probed ones did not.
"""

from . import Kind, Result


def read(ctx):
    if not ctx.conf or not ctx.conf.is_file():
        return Result.of(error=f"no config at {ctx.conf}")
    try:
        import yaml
    except ImportError:
        return Result.of(error="PyYAML not installed — showing literal rows only")
    try:
        with ctx.conf.open(encoding="utf-8", errors="replace") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        return Result.of(error=f"{ctx.conf.name}: {exc}")
    return Result.of(flatten_paths(data))


def flatten_paths(d, prefix=""):
    """`keybinding.universal.quit` — the dotted path is the action name, because
    that is how lazygit's own docs refer to a binding."""
    out = {}
    for k, v in (d or {}).items():
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_paths(v, path))
        elif isinstance(v, list):
            out[path] = [str(x) for x in v]
        elif v is not None:
            out[path] = [str(v)]
    return out


KIND = Kind("yaml-keys", read)
