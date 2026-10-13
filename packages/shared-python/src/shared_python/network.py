"""Where a request comes from, and whether a list of networks allows it (A6, W5).

An organisation can say "only from our offices": a list of networks, written
as addresses or ranges (``203.0.113.7``, ``10.0.0.0/8``, ``2001:db8::/32``).
The address of a request is the connecting address, unless the deployment
says how many proxies sit in front of it (``TRUSTED_PROXY_HOPS``), in which
case it is read from ``X-Forwarded-For`` that many hops back. Trusting the
header without a proxy would let anyone claim any address.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class NetworkListError(ValueError):
    """A list entry that is not an address or a range, said in words."""


def client_address(peer: str | None, forwarded_for: str | None, trusted_proxy_hops: int) -> str:
    """The address a request came from, as far as the deployment can trust."""
    if trusted_proxy_hops > 0 and forwarded_for:
        hops = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if hops:
            # Each trusted proxy appends the address it received from; the
            # client's own address is the one `trusted_proxy_hops` from the end.
            index = max(0, len(hops) - trusted_proxy_hops)
            return hops[index]
    return (peer or "").strip()


def parse_networks(entries: Iterable[str]) -> list[Network]:
    """Addresses and ranges, checked one by one, so a typo names its line."""
    networks: list[Network] = []
    for raw in entries:
        entry = str(raw).strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise NetworkListError(
                f"'{entry}' is not an address or a range. Write one like 203.0.113.7 or 10.0.0.0/8."
            ) from exc
    return networks


def address_allowed(address: str, networks: Sequence[Network]) -> bool:
    """True when the address falls inside any of the networks. An address that
    cannot be read is never allowed: refusing is the safe answer."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed.version == network.version and parsed in network for network in networks)
