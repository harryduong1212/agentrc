"""The one module that knows which machine this is.

Everywhere else asks this; nothing else branches on the OS. howto runs on
Linux, macOS and Windows, and each of those disagrees about four things:

  where config lives      ~/.config, or %APPDATA%
  how to start an editor  execvp replaces the process; Windows has no such thing
  what a shell is         $SHELL -ic alias, or `Get-Alias` under PowerShell
  whether curses exists   not in the Windows stdlib — it needs windows-curses

Named `host` and not `platform` so it cannot be confused with the stdlib module
of that name, which this file imports.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"

DEFAULT_TIMEOUT = 5  # config.toml overrides it; this is the floor if it cannot be read


def config_root():
    """Where *every* tool on this machine keeps its config — `~/.config`, or
    `%APPDATA%`. The one place the three OSes disagree, answered once.

    Read fresh each call, so a test can move HOME without reimporting.

    XDG_CONFIG_HOME wins everywhere when it is set — people who set it on
    Windows or macOS mean it. Otherwise: %APPDATA% on Windows, ~/.config on the
    other two, which is where macOS tools of this kind actually look despite
    ~/Library/Application Support being the platform answer.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg)
    if WINDOWS:
        return Path(os.environ.get("APPDATA") or (home() / "AppData" / "Roaming"))
    return home() / ".config"


def config_dir():
    """Where your own howto files live."""
    return config_root() / "howto"


def home():
    # HOME first so a test can move it; Path.home() reads the password database
    # on POSIX and USERPROFILE on Windows, neither of which a test can redirect.
    return Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())


def expand(p):
    """A config path from a data file -> an absolute path, or None."""
    if not p:
        return None
    s = os.path.expandvars(str(p))
    if s.startswith("~"):
        return home() / s[1:].lstrip("/\\")
    return Path(s)


def run(cmd, timeout=DEFAULT_TIMEOUT, **kw):
    """stdout+stderr, or None when the command is missing, fails or hangs.

    Every probe goes through here, so a tool that is absent on this machine is
    an empty pane and never a traceback.
    """
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            errors="replace", **kw
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "") + (r.stderr or "")
    return out if out.strip() else None


def which(name):
    return shutil.which(name) if name else None


def replace(source, target):
    os.replace(source, target)


def devnull_stdin():
    return subprocess.DEVNULL


def vim_redirect():
    """Where `vim -es` should redirect its message area.

    In silent ex mode `:map` writes to the message area, not to stdout, so
    without a redir the pipe is empty and vim looks like it has no mappings at
    all. Windows has no /dev/stdout, so there the probe writes a temp file and
    the caller reads it back.
    """
    return None if WINDOWS else "/dev/stdout"


def alias_command():
    """How to ask this machine's shell for its aliases, or None.

    cmd.exe has no aliases and PowerShell's are a different thing entirely
    (`Get-Alias` lists cmdlet nicknames, not user shortcuts), so Windows gets
    PowerShell's own list when pwsh is there, and nothing when it is not.
    """
    if WINDOWS:
        exe = which("pwsh") or which("powershell")
        if not exe:
            return None
        return [exe, "-NoProfile", "-Command", "Get-Alias | ForEach-Object { \"$($_.Name)=$($_.Definition)\" }"]
    sh = os.environ.get("SHELL") or "/bin/sh"
    return [sh, "-ic", "alias"]


def open_editor(path):
    """Hand the terminal to $EDITOR on this file, then come back.

    Not execvp: on Windows it does not replace the process, so the shell gets
    its prompt back while the editor is still starting and the two fight over
    the terminal. subprocess.call behaves the same way on all three.
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or default_editor()
    sys.stdout.flush()
    try:
        return subprocess.call(split_editor(editor) + [str(path)])
    except OSError as exc:
        print(f"could not start {editor!r}: {exc}", file=sys.stderr)
        print(f"the file is at {path}", file=sys.stderr)
        return 1


def default_editor():
    if WINDOWS:
        return "notepad"
    return which("vim") and "vim" or "vi"


def split_editor(editor):
    # EDITOR may carry flags ("code -w"). shlex would mangle a Windows path
    # with backslashes, so split on whitespace there and trust the simple case.
    if WINDOWS:
        return editor.split()
    import shlex

    return shlex.split(editor)


def curses_module():
    """The curses module, or None with a reason.

    On Windows this is the pip package `windows-curses`; there is no stdlib
    curses there. The CLI half of howto works without it, which is why this
    returns rather than raising at import time.
    """
    try:
        import curses

        return curses, ""
    except ImportError:
        if WINDOWS:
            return None, (
                "curses is not in the Windows stdlib.\n"
                "  pip install windows-curses\n"
                "or use the plain-text output: howto --list"
            )
        return None, "curses is unavailable in this Python build"


def describe():
    """One line for `howto where` and bug reports."""
    return f"{platform.system()} {platform.release()} · python {platform.python_version()}"
