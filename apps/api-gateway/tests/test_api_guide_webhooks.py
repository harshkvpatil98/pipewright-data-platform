"""The guide's signature check works as written (adoption-readiness A8, Y1).

`docs/user/api.md` gives a partner a Python function to check each event came
from Pipewright. This runs that exact code block against bodies signed the
way the platform signs them, so the guide and the sender cannot drift apart.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from service_notifications.senders import webhook_sender

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "user" / "api.md"


def _guide_function():
    section = GUIDE.read_text().split("## Webhooks", 1)[1].split("\n## ", 1)[0]
    [code] = re.findall(r"```python\n(.*?)```", section, flags=re.S)
    namespace: dict = {}
    exec(compile(code, str(GUIDE), "exec"), namespace)  # noqa: S102 - the guide's own code
    return namespace["came_from_pipewright"]


def test_the_guides_check_accepts_a_real_event_and_refuses_a_forged_one() -> None:
    check = _guide_function()
    body = b'{"id":"1","type":"workflow_run_failed"}'
    header = webhook_sender.signature_header("whsec_partner", body)
    assert check("whsec_partner", header, body)
    assert not check("whsec_partner", header, body.replace(b"failed", b"passed"))
    assert not check("whsec_someone_else", header, body)
    stale = webhook_sender.signature_header("whsec_partner", body, now=time.time() - 3600)
    assert not check("whsec_partner", stale, body)
