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


def _addr_host(entry):
    """Host part of an EPICS address-list entry: 'h', 'h:port', '[v6]', '[v6]:port', or a bare v6 literal."""
    e = entry.strip()
    if e.startswith('['):
        return e[1:].split(']', 1)[0]
    if e.count(':') == 1:
        return e.split(':', 1)[0]
    return e


def require_loopback_pva_env(environ, what='PVA client'):
    """Check the EPICS PV Access client environment before any PVA context exists.

    Accepted only when EPICS_PVA_AUTO_ADDR_LIST is NO (no broadcast to the subnet), the
    EPICS_PVA_ADDR_LIST is non-empty and every entry is a loopback address, and every
    EPICS_PVA_NAME_SERVERS entry (if any) is loopback.  Returns the dict of EPICS_PVA_*
    settings to hand to the client explicitly (p4p Context(conf=..., useenv=False)).
    """
    auto = (environ.get('EPICS_PVA_AUTO_ADDR_LIST') or '').strip()
    if auto.upper() != 'NO':
        raise NonLoopbackError('%s: EPICS_PVA_AUTO_ADDR_LIST=%r; refusing (must be NO, or PVA searches '
                               'broadcast beyond this host)' % (what, auto))
    addrs = (environ.get('EPICS_PVA_ADDR_LIST') or '').split()
    if not addrs:
        raise NonLoopbackError('%s: EPICS_PVA_ADDR_LIST is empty; refusing (must list loopback addresses only)'
                               % what)
    for key, entries in (('EPICS_PVA_ADDR_LIST', addrs),
                         ('EPICS_PVA_NAME_SERVERS', (environ.get('EPICS_PVA_NAME_SERVERS') or '').split())):
        for e in entries:
            host = _addr_host(e)
            if _is_loopback_literal(host) is not True:
                raise NonLoopbackError('%s: %s entry %r is not a loopback IP literal; refusing' % (what, key, e))
    conf = {'EPICS_PVA_AUTO_ADDR_LIST': 'NO', 'EPICS_PVA_ADDR_LIST': ' '.join(addrs)}
    for key in ('EPICS_PVA_NAME_SERVERS', 'EPICS_PVA_BROADCAST_PORT', 'EPICS_PVA_SERVER_PORT'):
        if environ.get(key):
            conf[key] = environ[key].strip()
    return conf
