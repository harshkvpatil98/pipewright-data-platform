"""One product version everywhere it is written (adoption-readiness A9, Z5).

Before the launch the gateway said 0.2.0, the web app 0.1.0, the client
0.2.0 and the Helm chart 0.1.0. A release has one number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from api_gateway.config import Settings

ROOT = Path(__file__).resolve().parents[3]


def _toml_version(path: Path) -> str:
    return re.search(r'^version = "([^"]+)"', path.read_text(), flags=re.M).group(1)


def test_every_part_of_the_product_says_the_same_version() -> None:
    chart = (ROOT / "deploy/helm/pipewright/Chart.yaml").read_text()
    lock = json.loads((ROOT / "package-lock.json").read_text())
    found = {
        "gateway (APP_VERSION default)": Settings.model_fields["app_version"].default,
        "gateway package": _toml_version(ROOT / "apps/api-gateway/pyproject.toml"),
        "web app": json.loads((ROOT / "apps/web/package.json").read_text())["version"],
        "web app (lock file)": lock["packages"]["apps/web"]["version"],
        "Python client": _toml_version(ROOT / "clients/python/pyproject.toml"),
        "Helm chart": re.search(r"^version: (\S+)", chart, flags=re.M).group(1),
        "Helm chart app": re.search(r'^appVersion: "([^"]+)"', chart, flags=re.M).group(1),
    }
    assert len(set(found.values())) == 1, found
