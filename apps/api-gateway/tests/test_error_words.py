"""Error messages people read use the product's words (adoption-readiness A5).

The web app's language lint covers what the pages say; this covers what the
API says when something is refused, since those messages are shown as they
are. It reads every `raise SomethingError("...")` in the services through the
Python parser, f-strings included.

Since A7 it also reads the other text the services hand to people (a run's
and a task's `message`, an incident's `title` and `summary`), and every
string for a count written "row(s)": 125 of them had been missed because
only raised errors were read.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [*sorted((ROOT / "services").glob("*/src")), ROOT / "packages" / "shared-python" / "src"]
GATEWAY = ROOT / "apps" / "api-gateway" / "src"

RETIRED = re.compile(
    r"\b(pipelines?|extraction|tenants?|materiali[sz]\w*|artifacts?|watermarks?|upserts?|snapshots?)\b",
    re.IGNORECASE,
)


def _message(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)
    return None


def _raised_messages():
    for source in SOURCES:
        for path in source.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                    continue
                name = getattr(node.exc.func, "id", getattr(node.exc.func, "attr", ""))
                if not name.endswith(("Error", "Exception")) or not node.exc.args:
                    continue
                text = _message(node.exc.args[0])
                if text:
                    yield f"{path.relative_to(ROOT)}:{node.lineno}", name, text


def test_it_reads_the_messages_it_means_to() -> None:
    assert sum(1 for _ in _raised_messages()) > 500


def test_refusals_people_see_use_the_products_words() -> None:
    # Errors meant for the people using the product: the ones the API returns.
    shown = ("BadRequestError", "NotFoundError", "ConflictError", "ForbiddenError", "InternalServerError")
    offenders = [
        f"{where}: {text}"
        for where, name, text in _raised_messages()
        if name in shown and RETIRED.search(text)
    ]
    assert offenders == []


def test_counts_are_written_out_not_marked_with_s() -> None:
    """"3 columns", never "column(s)": `shared_python.words` does the counting."""
    offenders = [f"{where}: {text}" for where, _name, text in _raised_messages() if "(s)" in text]
    assert offenders == []


#: In text handed to people, the A0 words: a check (not a rule or a gate), a
#: task (not a node), a schema change (not drift).
RETIRED_IN_MESSAGES = re.compile(RETIRED.pattern[:-3] + r"|nodes?|rules?|quality gate|drift gate)\b", re.IGNORECASE)


def _strings_people_read():
    """Every string literal except docstrings and log lines, with where it is."""
    for source in [*SOURCES, GATEWAY]:
        for path in source.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            skip: set[int] = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    skip.add(id(body[0].value))
                if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("debug", "info", "warning", "error", "exception"):
                    skip.update(id(part) for argument in node.args for part in ast.walk(argument))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                    yield f"{path.relative_to(ROOT)}:{node.lineno}", node.value


def test_no_count_anywhere_is_written_with_s() -> None:
    offenders = [f"{where}: {text[:80]}" for where, text in _strings_people_read() if "(s)" in text or "(ies)" in text]
    assert offenders == []


def test_run_task_and_incident_text_uses_the_products_words() -> None:
    offenders = []
    for source in SOURCES:
        for path in source.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                if isinstance(node, ast.keyword) and node.arg in ("message", "title", "summary"):
                    text = _message(node.value)
                    if text and RETIRED_IN_MESSAGES.search(text):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.value.lineno}: {text}")
    assert offenders == []
