#!/usr/bin/env python
"""Write the Python client's operations, and the API reference, from the
gateway's OpenAPI document.

    .venv/bin/python scripts/generate-client.py

Run it after changing the API; `clients/python/tests/test_client.py` fails
until you do. `docs/api/openapi.json` is the reference as of this commit
(A9, Z3): what a release's API was, without running that release.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "clients/python/src/pipewright/_operations.py"
REFERENCE = ROOT / "docs/api/openapi.json"


def spec() -> dict:
    for source in [ROOT / "apps/api-gateway/src", *ROOT.glob("services/*/src"), ROOT / "packages/shared-python/src"]:
        sys.path.insert(0, str(source))
    from api_gateway.main import app

    return app.openapi()


def _generator():
    """The renderer, loaded by file: the package itself imports what it writes."""
    import importlib.util

    module_spec = importlib.util.spec_from_file_location("_pipewright_generate", ROOT / "clients/python/src/pipewright/_generate.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> int:
    document = spec()
    generator = _generator()
    TARGET.write_text(generator.render(document))
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(generator.reference(document))
    print(f"Wrote {TARGET.relative_to(ROOT)} and {REFERENCE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
