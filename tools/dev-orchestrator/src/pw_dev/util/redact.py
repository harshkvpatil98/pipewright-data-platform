"""Keep credentials out of prompts, artifacts and logs.

Two different jobs live here. `redact` scrubs text the controller is about to
persist or show. `scan_for_secrets` refuses to let a staged diff be committed
when it looks like it carries a credential -- that one is a gate, not cosmetics.
"""

from __future__ import annotations

import re

# Patterns are deliberately conservative: a false negative publishes a secret.
#
# There is no override. A false positive refuses the commit and a person has to
# look at what matched -- which is the right trade, and it does happen: this
# package's own tests contain deliberately fake keys to prove the scanner works,
# so a run that tried to publish a change to them would stop and ask. That is a
# person reading a diff for thirty seconds, against the alternative of a
# credential reaching a public remote.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("bearer header", re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S{16,}")),
    ("assignment to a secret-looking name", re.compile(
        r"(?i)\b(?:secret|password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"client[_-]?secret|encryption[_-]?key)\b\s*[:=]\s*[\"']?[A-Za-z0-9/+_\-]{16,}"
    )),
]

REDACTED = "<redacted>"


def redact(text: str) -> str:
    """Replace anything matching a credential pattern with `<redacted>`."""
    for _, pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scan_for_secrets(text: str) -> list[tuple[str, str]]:
    """Return `(what, snippet)` for every credential-shaped match.

    The snippet is itself redacted, so calling this on a diff and printing the
    result does not print the secret.
    """
    hits: list[tuple[str, str]] = []
    for label, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            fragment = match.group(0)
            masked = fragment[:4] + REDACTED if len(fragment) > 8 else REDACTED
            hits.append((label, masked))
    return hits
