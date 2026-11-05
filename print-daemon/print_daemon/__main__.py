"""Allow ``python -m print_daemon``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
