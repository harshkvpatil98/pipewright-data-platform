#!/usr/bin/env python
"""Regenerate `docs/transformation-tools.md`, and the Studio's copy of what a
search reads of each tool, from the tool registry.

A test asserts the checked-in file matches this output, so running it is part of
adding a tool. Kept as a script rather than a build step because the reference
is reviewed in the diff -- seeing a new tool appear in the documentation is how
a reviewer notices one arrived without an example.
"""

from __future__ import annotations

import pathlib
import sys

from service_transformations.tools.docs import as_markdown, search_snapshot

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = (
    (ROOT / "docs" / "transformation-tools.md", as_markdown),
    (ROOT / "apps" / "web" / "src" / "features" / "studio" / "tools" / "search-catalogue.json", search_snapshot),
)


def main() -> int:
    for target, make in TARGETS:
        fresh = make()
        name = target.relative_to(ROOT)
        if target.exists() and target.read_text(encoding="utf-8") == fresh:
            print(f"{name} is already up to date.")
            continue
        target.write_text(fresh, encoding="utf-8")
        print(f"Wrote {name} ({len(fresh.splitlines())} lines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
