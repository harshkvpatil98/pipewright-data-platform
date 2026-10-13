"""The audit log's list of read-only POSTs must name routes that exist.

`READ_ONLY_POSTS` is matched by path skeleton, so a renamed route would
silently fall out of it (and start filling the log again) while a typo would
never match anything. Checking the list against the real route table keeps
both mistakes visible.
"""

import re

from api_gateway.main import app
from service_governance.audit import READ_ONLY_POSTS


def _post_skeletons() -> set[str]:
    # Read from the OpenAPI document rather than `app.routes`, which holds
    # included routers as opaque entries rather than flattened routes.
    paths = app.openapi()["paths"]
    return {
        re.sub(r"\{[^}]+\}", "{id}", path)
        for path, operations in paths.items()
        if "post" in operations
    }


def test_every_read_only_post_is_a_real_route() -> None:
    missing = sorted(READ_ONLY_POSTS - _post_skeletons())
    assert not missing, f"not a POST route in the gateway: {missing}"
