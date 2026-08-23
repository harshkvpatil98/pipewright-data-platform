#!/usr/bin/env python
"""Regenerate `docs/transformation-tools.md` from the tool registry.

A test asserts the checked-in file matches this output, so running it is part of
adding a tool. Kept as a script rather than a build step because the reference
is reviewed in the diff -- seeing a new tool appear in the documentation is how
a reviewer notices one arrived without an example.
"""

from __future__ import annotations

import pathlib
import sys

from service_transformations.tools.docs import as_markdown

TARGET = pathlib.Path(__file__).resolve().parents[1] / "docs" / "transformation-tools.md"


def main() -> int:
    fresh = as_markdown()
    if TARGET.exists() and TARGET.read_text(encoding="utf-8") == fresh:
        print(f"{TARGET.relative_to(TARGET.parents[1])} is already up to date.")
        return 0
    TARGET.write_text(fresh, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(TARGET.parents[1])} ({len(fresh.splitlines())} lines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
