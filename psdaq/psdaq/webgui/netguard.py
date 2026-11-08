"""Loopback-only network guard for the DAQ web GUI server.

Every address the server binds to and every endpoint it may contact (the
control host's ZMQ ports, the config DB URL, the events URL) goes through
these checks before anything is opened.  A host is accepted only when every
address it resolves to is a loopback address (127.0.0.0/8 or ::1).
"""

import ipaddress
import socket
from urllib.parse import urlsplit


class NonLoopbackError(ValueError):
    """Raised when an address or URL would leave the local host."""


def _is_loopback_literal(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return None  # not an IP literal


def resolve_addresses(host):
    """Return the set of IP strings `host` resolves to (no network for literals)."""
    lit = _is_loopback_literal(host)
    if lit is not None:
        return {str(ipaddress.ip_address(host))}
    infos = socket.getaddrinfo(host, None)
    return {info[4][0] for info in infos}


def is_loopback_host(host):
    """True when `host` is non-empty and every address it resolves to is loopback."""
    if not host:
        return False
    host = host.strip('[]')
    lit = _is_loopback_literal(host)
    if lit is not None:
        return lit
    # only names that are conventionally loopback are looked up; anything else
    # is refused without a DNS query (no off-host lookups)
    if host not in ('localhost', 'localhost.localdomain', 'ip6-localhost', 'ip6-loopback'):
        return False
    try:
        addrs = resolve_addresses(host)
    except OSError:
        return False
    return bool(addrs) and all(ipaddress.ip_address(a.split('%')[0]).is_loopback for a in addrs)


def require_loopback_host(host, what):
    if not is_loopback_host(host):
        raise NonLoopbackError('%s: host %r is not a loopback address; refusing (the web GUI only talks to 127.0.0.1)'
                               % (what, host))
    return host


def require_loopback_url(url, what, schemes=('http', 'https')):
    """Check that `url` uses one of `schemes` and points at a loopback host."""
    parts = urlsplit(url)
    if parts.scheme not in schemes:
        raise NonLoopbackError('%s: URL %r has scheme %r, expected one of %s' % (what, url, parts.scheme, schemes))
    require_loopback_host(parts.hostname or '', '%s (%s)' % (what, url))
    return url
