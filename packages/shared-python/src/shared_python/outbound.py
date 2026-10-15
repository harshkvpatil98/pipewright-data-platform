"""Which addresses the platform's connectors may call.

A connector that fetches a URL someone typed is a way to make the server call
addresses only it can reach. Three tiers:

- Always refused: link-local addresses (169.254.0.0/16, fe80::/10), which is
  where cloud metadata services hand out credentials, plus multicast,
  reserved and unspecified addresses.
- Refused unless OUTBOUND_ALLOW_LOOPBACK=true: loopback (127.0.0.0/8, ::1),
  the platform's own machine.
- Allowed unless OUTBOUND_BLOCK_PRIVATE_NETWORKS=true: private networks
  (10/8, 172.16/12, 192.168/16, fc00::/7). Self-hosted deployments read
  internal APIs all the time; one that does not can close them.

The host is resolved and every address it resolves to is checked, on every
request including redirects. A name that changes its answer between the
check and the connection (DNS rebinding) is not covered; this closes the
direct route, which is the one people try.
"""

from __future__ import annotations

import ipaddress
import os
import socket


class OutboundBlocked(ValueError):
    """An address the platform will not call."""


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _refusal(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    # Loopback first: Python counts ::1 as reserved too, and judged as reserved it
    # was refused even with loopback allowed, so `localhost` on a machine where it
    # means ::1 could never be reached.
    if address.is_loopback:
        return None if _flag("OUTBOUND_ALLOW_LOOPBACK") else "this server itself"
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        return "an internal address the platform never calls"
    if address.is_private and not address.is_loopback and _flag("OUTBOUND_BLOCK_PRIVATE_NETWORKS"):
        return "a private network address, which this deployment does not allow"
    return None


def check_host(host: str) -> None:
    """Raise OutboundBlocked when `host` resolves to an address the platform must not call."""
    name = (host or "").strip().strip("[]")
    if not name:
        raise OutboundBlocked("There is no address to call.")
    try:
        candidates = {ipaddress.ip_address(name)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(name, None)
        except socket.gaierror as exc:
            raise OutboundBlocked(f"'{name}' could not be found.") from exc
        candidates = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    for address in candidates:
        reason = _refusal(address)
        if reason:
            raise OutboundBlocked(f"'{name}' points to {reason} ({address}).")


def httpx_request_guard(request) -> None:
    """An httpx request hook: checks every request, redirects included."""
    check_host(request.url.host)
