"""Shared fixtures for the connector tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _outbound_loopback_allowed(monkeypatch):
    """The contract tests serve recorded vendor responses from a local HTTP
    server, which the outbound guard refuses by default (it is this machine).
    Tests of the guard itself clear this again."""
    monkeypatch.setenv("OUTBOUND_ALLOW_LOOPBACK", "true")
