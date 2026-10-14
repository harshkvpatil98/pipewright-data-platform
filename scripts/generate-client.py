#!/usr/bin/env python
"""Write the Python client's operations from the gateway's OpenAPI document.

    .venv/bin/python scripts/generate-client.py

Run it after changing the API; `clients/python/tests/test_generated.py`
fails until you do.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "clients/python/src/pipewright/_operations.py"


def spec() -> dict:
    for source in [ROOT / "apps/api-gateway/src", *ROOT.glob("services/*/src"), ROOT / "packages/shared-python/src"]:
        sys.path.insert(0, str(source))
    from api_gateway.main import app

    return app.openapi()


def render(document: dict) -> str:
    """The renderer, loaded by file: the package itself imports what it writes."""
    import importlib.util

    module_spec = importlib.util.spec_from_file_location("_pipewright_generate", ROOT / "clients/python/src/pipewright/_generate.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module.render(document)


def main() -> int:
    TARGET.write_text(render(spec()))
    print(f"Wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
