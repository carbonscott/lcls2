"""The web GUI server's Host-header and Origin refusals (server.py make_handler: _host_ok, do_GET, do_POST).

- Every GET and POST whose Host header is not loopback gets 403 {"error": "Host header must be loopback"}
  before any routing (DNS-rebinding guard: a page on evil.example that re-points its name at
  127.0.0.1 still sends Host: evil.example:<port>).
- A POST whose Origin header is present, not "null", and whose host:port differs from the Host header
  gets 403 {"error": "cross-origin request refused"}, before the body is read or a route runs.
- Origin "null" (sandboxed iframes, file:// pages, some redirects) is NOT refused by the Origin check.
  What stops such a page is the next gate and the browser: the server accepts only
  Content-Type application/json (anything else: 415), and a cross-origin JSON POST needs a CORS
  preflight (OPTIONS), which this server does not implement (501, no Access-Control-Allow-* header),
  so a browser never sends the POST.  A non-browser client on the node can send anything: the server
  has no authentication (README / RUNBOOK §7).
- A refused POST changes nothing (checked on /api/record against the emulator's recording flag).

No browser needed: plain http.client against `daq_webgui --emulate` on 127.0.0.1.
"""

import http.client
import json
import socket
import time
from urllib.parse import urlsplit

import pytest

from webgui_harness import ServerProc


@pytest.fixture(scope='module')
def web():
    s = ServerProc(['--emulate', '--emulate-slow', '0.05']).start()
    u = urlsplit(s.url)
    s.port = u.port
    s.hostport = '127.0.0.1:%d' % u.port
    yield s
    s.stop()


def request(web, method, path, headers=None, body=None, host=None):
    """One request with exactly these headers (http.client adds no Host when one is given)."""
    c = http.client.HTTPConnection('127.0.0.1', web.port, timeout=10)
    try:
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        h = {'Host': web.hostport if host is None else host}
        h.update(headers or {})
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        if data is not None:
            h['Content-Length'] = str(len(data))
        for k, v in h.items():
            if v is not None:
                c.putheader(k, v)
        c.endheaders(data)
        r = c.getresponse()
        raw = r.read()
        try:
            j = json.loads(raw) if raw else None
        except ValueError:
            j = None
        return r.status, j, dict(r.getheaders()), raw
    finally:
        c.close()


def _host_ip():
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        return None
    return None if ip.startswith('127.') else ip


JSON = {'Content-Type': 'application/json'}


def recording_after(web, want=None, timeout=5.0):
    """The emulator's recording flag; with want, wait (setRecord runs in a job) until it equals want."""
    end = time.monotonic() + timeout
    while True:
        cur = web.get('/api/status')['recording']
        if want is None or cur == want or time.monotonic() > end:
            return cur
        time.sleep(0.05)


# ---------------- Host header ----------------

@pytest.mark.parametrize('host', ['127.0.0.1:{port}', '127.0.0.1', 'localhost:{port}', '[::1]:{port}',
                                  '127.1.2.3:{port}'])
def test_get_loopback_host_accepted(web, host):
    code, j, _, _ = request(web, 'GET', '/api/meta', host=host.format(port=web.port))
    assert code == 200, (host, code, j)
    assert j['backend'] == 'emulator'


@pytest.mark.parametrize('host', ['evil.example:{port}', 'evil.example', 'sdfmilan119:{port}',
                                  '127.0.0.1.evil.example:{port}', '0.0.0.0:{port}', 'HOSTIP:{port}', ''])
@pytest.mark.parametrize('path', ['/', '/api/meta', '/api/status', '/api/nonexistent'])
def test_get_non_loopback_host_refused(web, host, path):
    if 'HOSTIP' in host:
        ip = _host_ip()
        if ip is None:
            pytest.skip('host has no non-loopback IPv4 address')
        host = host.replace('HOSTIP', ip)
    code, j, _, _ = request(web, 'GET', path, host=host.format(port=web.port))
    assert code == 403, (host, path, code, j)
    assert j == {'error': 'Host header must be loopback'}


def test_get_without_host_header_refused(web):
    c = http.client.HTTPConnection('127.0.0.1', web.port, timeout=10)
    try:
        c.putrequest('GET', '/api/meta', skip_host=True, skip_accept_encoding=True)
        c.endheaders()
        r = c.getresponse()
        assert r.status == 403 and json.loads(r.read()) == {'error': 'Host header must be loopback'}
    finally:
        c.close()


@pytest.mark.parametrize('origin', [None, 'http://{hp}'])
def test_post_non_loopback_host_refused_before_origin(web, origin):
    """Host is checked first: a foreign Host is refused even with a matching Origin."""
    h = dict(JSON, Origin=None if origin is None else origin.format(hp='evil.example:%d' % web.port))
    code, j, _, _ = request(web, 'POST', '/api/record', h, {'record': True}, host='evil.example:%d' % web.port)
    assert code == 403 and j == {'error': 'Host header must be loopback'}, (code, j)


# ---------------- Origin header (POST) ----------------

@pytest.mark.parametrize('origin', ['http://evil.example', 'http://evil.example:{port}', 'https://evil.example',
                                    'http://127.0.0.1:{other}', 'http://localhost:{port}', 'http://127.0.0.1',
                                    'http://[::1]:{port}'])
def test_post_foreign_origin_refused(web, origin):
    o = origin.format(port=web.port, other=web.port + 1)
    for path in ('/api/record', '/api/state', '/api/nonexistent'):
        code, j, _, _ = request(web, 'POST', path, dict(JSON, Origin=o), {'record': True, 'state': 'unallocated'})
        assert code == 403, (o, path, code, j)
        assert j == {'error': 'cross-origin request refused'}


def test_post_foreign_origin_has_no_effect(web):
    before = recording_after(web)
    code, j, _, _ = request(web, 'POST', '/api/record', dict(JSON, Origin='http://evil.example'),
                            {'record': not before})
    assert code == 403, (code, j)
    time.sleep(0.5)                                     # a job that ran would have flipped it by now
    assert recording_after(web) == before
    code, j, _, _ = request(web, 'POST', '/api/state', dict(JSON, Origin='http://evil.example'),
                            {'state': 'unallocated'})
    assert code == 403 and web.get('/api/status')['state'] == 'reset', (code, j)


@pytest.mark.parametrize('origin', [None, 'http://{hp}'])
def test_post_same_origin_or_none_accepted(web, origin):
    """No Origin (curl, the e2e's own clients) or the page's own origin: the request is routed."""
    h = dict(JSON, Origin=None if origin is None else origin.format(hp=web.hostport))
    code, j, _, _ = request(web, 'POST', '/api/nonexistent', h, {})
    assert code == 404 and j == {'error': 'not found'}, (code, j)
    cur = recording_after(web)
    code, j, _, _ = request(web, 'POST', '/api/record', h, {'record': not cur})
    assert code == 200 and j['ok'] is True, (code, j)
    assert recording_after(web, not cur) is (not cur)
    code, j, _, _ = request(web, 'POST', '/api/record', h, {'record': cur})
    assert code == 200 and j['ok'] is True, (code, j)
    assert recording_after(web, cur) is cur


def test_origin_null_is_not_refused(web):
    """Origin 'null' passes the Origin check (server.py do_POST: `if origin and origin != 'null'`)."""
    code, j, _, _ = request(web, 'POST', '/api/nonexistent', dict(JSON, Origin='null'), {})
    assert code == 404 and j == {'error': 'not found'}, (code, j)   # routed, not 403
    cur = recording_after(web)
    code, j, _, _ = request(web, 'POST', '/api/record', dict(JSON, Origin='null'), {'record': not cur})
    assert code == 200 and j['ok'] is True, (code, j)
    assert recording_after(web, not cur) is (not cur)                 # the command ran
    request(web, 'POST', '/api/record', dict(JSON, Origin='null'), {'record': cur})
    assert recording_after(web, cur) is cur


@pytest.mark.parametrize('ctype', ['text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data; b=x',
                                   None])
@pytest.mark.parametrize('origin', ['null', None])
def test_simple_request_content_types_refused(web, ctype, origin):
    """The only POSTs a browser sends cross-origin without a preflight ('simple' requests) carry one of
    these content types: all get 415, so an Origin-null page cannot use them either."""
    cur = recording_after(web)
    code, j, _, _ = request(web, 'POST', '/api/record', {'Content-Type': ctype, 'Origin': origin},
                            json.dumps({'record': not cur}).encode())
    assert code == 415 and j == {'error': 'Content-Type must be application/json'}, (code, j)
    assert recording_after(web) == cur


@pytest.mark.parametrize('origin', ['null', 'http://evil.example'])
def test_no_cors_preflight(web, origin):
    """A cross-origin application/json POST needs a CORS preflight; the server has no OPTIONS handler
    (501) and grants no Access-Control-Allow-* header, so a browser does not send the POST."""
    code, _, headers, _ = request(web, 'OPTIONS', '/api/record',
                                  {'Origin': origin, 'Access-Control-Request-Method': 'POST',
                                   'Access-Control-Request-Headers': 'content-type'})
    assert code == 501, code
    assert not [k for k in headers if k.lower().startswith('access-control-')], headers
    for path in ('/api/meta', '/api/status'):
        code, _, headers, _ = request(web, 'GET', path, {'Origin': origin})
        assert code == 200 and not [k for k in headers if k.lower().startswith('access-control-')], headers
