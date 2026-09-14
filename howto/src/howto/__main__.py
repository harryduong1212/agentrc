import sys

from . import cli, host


def run():
    result = cli.cli(sys.argv[1:])
    if result is not None:
        return result
    curses, reason = host.curses_module()
    if curses is None:
        print(reason, file=sys.stderr)
        return 1
    from . import app

    try:
        curses.wrapper(app.main)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(run())
