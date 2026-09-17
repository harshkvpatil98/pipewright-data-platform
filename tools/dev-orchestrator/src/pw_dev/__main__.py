"""`python -m pw_dev` — same entry point as the `pw-dev` console script."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
