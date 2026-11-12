"""Single entry point of the packaged app: the UI server, or one translation."""

import sys


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ui"
    if mode in ("translate", "ui"):
        del sys.argv[1]
    if mode == "translate":
        from .cli import main as run
    else:
        from .web import main as run
    run()


if __name__ == "__main__":
    main()
