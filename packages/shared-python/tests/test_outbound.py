from __future__ import annotations

import socket

import pytest

from shared_python.outbound import OutboundBlocked, check_host


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_LOOPBACK", raising=False)
    monkeypatch.delenv("OUTBOUND_BLOCK_PRIVATE_NETWORKS", raising=False)


@pytest.mark.parametrize("host", ["169.254.169.254", "fe80::1", "0.0.0.0", "224.0.0.1"])
def test_metadata_and_other_internal_addresses_are_always_refused(host, monkeypatch) -> None:
    monkeypatch.setenv("OUTBOUND_ALLOW_LOOPBACK", "true")
    with pytest.raises(OutboundBlocked):
        check_host(host)


def test_loopback_is_refused_unless_allowed(monkeypatch) -> None:
    with pytest.raises(OutboundBlocked, match="this server itself"):
        check_host("127.0.0.1")
    monkeypatch.setenv("OUTBOUND_ALLOW_LOOPBACK", "true")
    check_host("127.0.0.1")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_ipv6_loopback_is_loopback_not_a_reserved_address(host, monkeypatch) -> None:
    """Python counts ::1 as reserved as well as loopback. Checked as reserved
    first, it was refused even with loopback allowed, so `localhost` -- which
    resolves to ::1 on many machines -- could never be reached (D1)."""
    monkeypatch.setenv("OUTBOUND_ALLOW_LOOPBACK", "true")
    check_host(host)
    monkeypatch.delenv("OUTBOUND_ALLOW_LOOPBACK")
    with pytest.raises(OutboundBlocked, match="this server itself"):
        check_host(host)


def test_private_networks_are_allowed_unless_closed(monkeypatch) -> None:
    check_host("10.0.0.5")
    monkeypatch.setenv("OUTBOUND_BLOCK_PRIVATE_NETWORKS", "true")
    with pytest.raises(OutboundBlocked, match="private network"):
        check_host("192.168.1.10")


def test_a_name_is_judged_by_every_address_it_resolves_to(monkeypatch) -> None:
    def fake(name, *_args, **_kwargs):
        return [(socket.AF_INET, None, None, "", ("93.184.216.34", 0)), (socket.AF_INET, None, None, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(OutboundBlocked, match="metadata.example"):
        check_host("metadata.example")


def test_a_public_address_is_allowed() -> None:
    check_host("93.184.216.34")
