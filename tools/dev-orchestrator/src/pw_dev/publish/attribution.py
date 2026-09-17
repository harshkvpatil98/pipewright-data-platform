"""Keeps assistant attribution out of Git metadata.

The distinction this module is built around: a provider's name inside *source
code and documentation* is a technical fact and must stay -- this repository
contains `codex_cli.py` and `claude_cli.py`, and removing those names would
break the code. A provider's name in *commit metadata, a branch, a tag, or a
Git note* is an authorship claim, and this project's commits are the owner's.

So the patterns below are matched against authorship surfaces only, and
`scan_text` is never applied to a diff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TRAILERS = re.compile(
    r"(?im)^\s*(?:co-authored-by|signed-off-by|generated-by|assisted-by|"
    r"authored-by|reviewed-by|on-behalf-of)\s*:\s*(?P<value>.+)$"
)

#: Matched in authorship surfaces.
#:
#: `\b` is the right boundary here, not a character class excluding hyphens: a
#: branch called `codex-generated-fix` and a trailer reading `Claude-authored`
#: are both attribution, and treating the hyphen as part of the word would let
#: them through. `\b` still keeps "claudication" from matching, because there is
#: no boundary between "claude" and the "i" that follows.
_ASSISTANT_TERMS = re.compile(
    r"(?i)(?:"
    r"\b(?:claude|anthropic|openai|codex|chatgpt|gpt-\d|copilot|cursor|devin)\b"
    r"|\bai[- ]generated\b|\bgenerated (?:with|by) ai\b|\bwritten by (?:an )?ai\b"
    r"|\bbot@|noreply@anthropic|noreply@openai|\[bot\]"
    r")"
)

_GENERATED_MARKERS = re.compile(
    r"(?i)(🤖|generated with \[|co-authored-by\s*:\s*claude|"
    r"this commit was (?:created|generated) by)"
)


@dataclass(frozen=True)
class AttributionFinding:
    surface: str
    value: str
    reason: str

    def __str__(self) -> str:
        return f"{self.surface}: {self.reason} ({self.value!r})"


def scan_text(text: str, surface: str) -> list[AttributionFinding]:
    """Scan one authorship surface: a commit subject, body, trailer or ref name."""
    findings: list[AttributionFinding] = []
    if not text:
        return findings

    for match in _TRAILERS.finditer(text):
        value = match.group("value").strip()
        keyword = match.group(0).split(":", 1)[0].strip().lower()
        if keyword in ("co-authored-by", "generated-by", "assisted-by"):
            findings.append(AttributionFinding(
                surface, value,
                f"'{keyword}' trailers are not used in this repository's history",
            ))
        elif _ASSISTANT_TERMS.search(value):
            findings.append(AttributionFinding(
                surface, value, f"'{keyword}' trailer names an assistant or provider",
            ))

    for match in _GENERATED_MARKERS.finditer(text):
        findings.append(AttributionFinding(
            surface, match.group(0), "carries a generated-by marker",
        ))

    for match in _ASSISTANT_TERMS.finditer(text):
        # A term already reported through a trailer is not reported twice.
        if any(match.group(0).lower() in f.value.lower() for f in findings):
            continue
        findings.append(AttributionFinding(
            surface, match.group(0),
            "names an assistant or model provider in commit metadata, which reads as "
            "an authorship claim",
        ))
    return findings


def scan_commit_metadata(metadata: dict[str, str], *, sha: str) -> list[AttributionFinding]:
    """Scan one commit's author, committer, subject and body."""
    findings: list[AttributionFinding] = []
    short = sha[:12]
    for field in ("author_name", "author_email", "committer_name", "committer_email"):
        value = metadata.get(field, "")
        if value and _ASSISTANT_TERMS.search(value):
            findings.append(AttributionFinding(
                f"{short}.{field}", value,
                "the identity names an assistant or provider",
            ))
    findings += scan_text(metadata.get("subject", ""), f"{short}.subject")
    findings += scan_text(metadata.get("body", ""), f"{short}.body")
    return findings


def scan_ref_name(name: str, kind: str = "branch") -> list[AttributionFinding]:
    """Branches and tags are published names; they carry attribution too."""
    if not name:
        return []
    if _ASSISTANT_TERMS.search(name):
        return [AttributionFinding(kind, name, f"the {kind} name references an assistant or provider")]
    return []


def clean_commit_message(subject: str, body: str = "") -> str:
    """Build the message the publisher will use.

    Only the deterministic publisher composes commit messages. A worker's prose
    never becomes a commit message, which is the simplest way to guarantee no
    model writes this repository's history.
    """
    message = subject.strip()
    if body.strip():
        message += "\n\n" + body.strip()
    findings = scan_text(message, "composed message")
    if findings:
        raise ValueError(
            "the composed commit message carries attribution: "
            + "; ".join(str(f) for f in findings)
        )
    return message + "\n"
