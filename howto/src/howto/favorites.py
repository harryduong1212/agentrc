"""spf's `sidebar/pinned.go`, as functions over a tuple.

Load / Save / Toggle / **Clean**, where Load drops entries whose target is gone
and re-saves. A favourite whose file you deleted should not keep a slot at the
top of the list forever.

The names are an immutable tuple and every operation returns a new one; the file
write is the only side effect, and it is the return value of the two functions
that do it, so a failed write is visible rather than assumed.
"""

import json
import os
import tempfile

from . import host


def path():
    return host.config_dir() / "favorites.json"


def read(known):
    """(names, changed) — `changed` is true when Clean dropped something, which
    is the signal to persist. Pure: it decides, it does not write."""
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
        names = tuple(str(x) for x in raw) if isinstance(raw, list) else ()
    except (OSError, ValueError):
        names = ()
    kept = tuple(n for n in names if n in known)
    return tuple(sorted(set(kept))), len(kept) != len(names)


def write(names):
    temporary = ""
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=p.parent, prefix=".favorites-", delete=False
        ) as output:
            output.write(json.dumps(list(names), indent=2) + "\n")
            temporary = output.name
        host.replace(temporary, p)
        return True
    except OSError:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return False


def load(known):
    names, changed = read(known)
    if changed:
        write(names)  # Clean: the drop is persisted, not merely hidden
    return names


def toggled(names, name):
    # spf's Toggle appends, so its pinned list is in insertion order. A
    # deliberate deviation: sorted here, because what you see should not depend
    # on the order you pressed P.
    rest = [n for n in names if n != name]
    return tuple(sorted(rest if name in names else rest + [name]))


def toggle(names, name):
    """(names, saved) — the app keeps the names, and reports when the disk
    refused them."""
    out = toggled(names, name)
    return out, write(out)
