"""Client IP resolution for per-IP limits (docs/api.md section 9, DCE_TRUSTED_PROXIES).

X-Forwarded-For is honoured only when the direct peer is in the trusted list. The client is the rightmost
address that is NOT trusted: each proxy appends the address it received from, so entries to the right of the
first untrusted one were written by trusted hops, and the untrusted one is the client they saw.
"""

from __future__ import annotations

import ipaddress

from app.config import IPNetwork


def _parse_ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def _is_trusted(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, trusted: tuple[IPNetwork, ...]) -> bool:
    return any(addr.version == net.version and addr in net for net in trusted)


def resolve_client_ip(peer: str | None, forwarded_for: str | None, trusted: tuple[IPNetwork, ...]) -> str:
    """Return the client address for rate limiting.

    - No trusted proxies configured, or the peer is not trusted: the peer address is used and XFF is ignored.
    - Trusted peer: walk XFF from the right, skipping trusted hops; the first untrusted entry is the client.
      A malformed entry is never trusted, so the peer address is used instead.
    - Trusted peer with every XFF entry trusted: the leftmost entry is the client.
    """
    fallback = peer or "unknown"
    if not trusted or not forwarded_for:
        return fallback
    peer_ip = _parse_ip(peer or "")
    if peer_ip is None or not _is_trusted(peer_ip, trusted):
        return fallback

    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    if not hops:
        return fallback
    leftmost = hops[0]
    for hop in reversed(hops):
        addr = _parse_ip(hop)
        if addr is None:
            return fallback
        if not _is_trusted(addr, trusted):
            return str(addr)
    leftmost_ip = _parse_ip(leftmost)
    return str(leftmost_ip) if leftmost_ip is not None else fallback
