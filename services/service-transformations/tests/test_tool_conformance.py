"""The tool library's checks as a function (X1) agree with the test suite.

`tools.conformance.check_tool` is what a plugin's tools are held to; it must
pass every built-in tool, as `test_tool_library.py` does, and fail a tool
that is wrong in the ways that suite catches.
"""

from __future__ import annotations

import dataclasses

import pytest

from service_transformations import tools
from service_transformations.tools.conformance import check_tool


@pytest.fixture(autouse=True)
def _token_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_every_built_in_tool_passes() -> None:
    failing = {name: report.failures for name, spec in tools.TOOLS.items() if not (report := check_tool(spec)).ok}
    assert failing == {}


def test_a_wrong_example_and_an_unfindable_title_fail() -> None:
    spec = tools.TOOLS["text.upper"]
    wrong = dataclasses.replace(spec, example=dataclasses.replace(spec.example, expect=("nope",) * len(spec.example.expect)))
    report = check_tool(wrong)
    assert any(failure.startswith("its example gives what it says") for failure in report.failures)
    hidden = dataclasses.replace(spec, name="text.upper_hidden", title="Zzqx", summary="No full stop")
    report = check_tool(hidden)
    assert "can be found by its own title" in report.failures
    assert "says what it does in a sentence" in report.failures
