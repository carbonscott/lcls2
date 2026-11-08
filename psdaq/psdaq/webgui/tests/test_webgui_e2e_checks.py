"""Unit tests of `daq_sim e2e`'s own checks (psdaq.webgui.e2e), without a DAQ, a server or a browser.

They show that the checks can fail:
- assertion 1 (gate): a counter that stalls after a DRP kill fails it, whether the stall lands below
  events * 1.1 (the "1082 < 1100" case) or above it (a later kill, or a small --events);
- assertion 6: one count that differs from the others fails it and is named (MISMATCH: ...);
- assertion 7: the DRP's Configure read must be in the window, logged with the expected seed, by the
  DRP's pid, with no page request to /api/configdb in the window, and an edit must have been saved;
- --break truncate-xtc2 cuts an xtc2 file at a datagram boundary, dropping only the tail.
"""

import argparse
import json
import struct
import sys

import pytest

from webgui_harness import PKG_ROOT

sys.path.insert(0, str(PKG_ROOT))
from psdaq.webgui import e2e  # noqa: E402
from psdaq.sim import daq_sim as ds  # noqa: E402


def args(**kw):
    a = dict(events=1000, edit_seed=None, expect_seed=None, breakage=None, timeout=60)
    a.update(kw)
    return argparse.Namespace(**a)


def state(**kw):
    s = {'platform': 5, 'seed': 0x1234, 'rate': 1000.0, 'ports': ds.ports(5), 'procs': {}}
    s.update(kw)
    return s


def run(tmp_path, **kw):
    return e2e.Run(args(**kw), ds.Work(str(tmp_path)), state())


# ---------------- assertion 1 ----------------

class Clock:
    """Fake time for e2e's module: sleep advances it, monotonic reads it."""

    def __init__(self):
        self.t = 0.0

    def sleep(self, dt):
        self.t += dt

    def monotonic(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(e2e.time, 'sleep', c.sleep)
    monkeypatch.setattr(e2e.time, 'monotonic', c.monotonic)
    return c


def counter(clock, rate=1000.0, t0=0.0, stall=None):
    """NumL0Acc: rate * (t - t0), stopping at stall (credit deadtime after a DRP kill)."""
    def read():
        n = int(max(0.0, clock.t - t0) * rate)
        return n if stall is None else min(n, stall)
    return read


@pytest.mark.parametrize('events,stall,ok', [
    (1000, None, True),         # a clean run: reaches 1100, then +2000 in 2 s
    (1000, 1082, False),        # kill ~70 ms after Enable: stalls below 1100 (the iteration-3 case)
    (1000, 1150, False),        # a later kill: stalls just above 1100, the rate check fails
    (1000, 2000, False),        # stall 0.5 s after the poll that saw 1500: +500 < 1000
    (100, 1082, False),         # small --events: sees 500 >= 110 early, then stalls: +582 < 1000
    (5000, None, True),
])
def test_gate(tmp_path, clock, events, stall, ok):
    r = run(tmp_path, events=events)
    r.pv_count = counter(clock, stall=stall)
    need = int(-(-events * 11 // 10))
    assert r.gate(need) is ok
    assert r.res[1][0] is ok
    print(r.res[1][1])


def test_gate_counter_unreadable(tmp_path, clock):
    r = run(tmp_path)
    r.pv_count = lambda: None
    assert r.gate(1100) is False and 'read None < 1100' in r.res[1][1]


# ---------------- assertion 6 ----------------

def finish_with(tmp_path, monkeypatch, gui=1531, teb=1531, ps_events=1531, ps_data=1531, direct=1531,
                checks='PASS', **kw):
    r = run(tmp_path, **kw)
    r.rows = [(s, 't', 't', 't', True) for s in e2e.UP + e2e.DOWN]
    r.info.update(gui=str(gui), prom={'TEB_WrtCt': teb}, count_after_disable=direct, run_control=1,
                  experiment='tstx00001', run_dom='1', exp_dom='tstx00001')
    seen = {}

    def fake_psana(work, st, exp, runnum, seed=None):
        seen['seed'] = seed
        return {'psana2 events': ps_events, 'psana2 with data': ps_data, 'psana2 checks': checks}
    monkeypatch.setattr(ds, '_psana_counts', fake_psana)
    r.finish()
    return r, seen


def test_counts_equal_pass(tmp_path, monkeypatch):
    r, seen = finish_with(tmp_path, monkeypatch)
    assert r.res[6][0], r.res[6]
    assert seen['seed'] == 0x1234 and 'MISMATCH' not in r.res[6][1]


@pytest.mark.parametrize('field,value,name', [
    ('ps_events', 1431, 'psana2 events 1431 != page 1531'),
    ('ps_data', 1530, 'psana2 with data 1530 != page 1531'),
    ('teb', 1532, 'TEB_WrtCt 1532 != page 1531'),
    ('direct', 1600, 'own NumL0Acc after Disable 1600 != page 1531'),
])
def test_one_count_off_fails_and_is_named(tmp_path, monkeypatch, field, value, name):
    r, _ = finish_with(tmp_path, monkeypatch, **{field: value})
    assert not r.res[6][0]
    assert 'MISMATCH: ' + name in r.res[6][1], r.res[6][1]
    assert r.res[2][0]


def test_page_count_off_fails(tmp_path, monkeypatch):
    r, _ = finish_with(tmp_path, monkeypatch, gui=1530)
    assert not r.res[6][0] and 'TEB_WrtCt 1531 != page 1530' in r.res[6][1]


def test_below_events_fails(tmp_path, monkeypatch):
    r, _ = finish_with(tmp_path, monkeypatch, gui=999, teb=999, ps_events=999, ps_data=999, direct=999)
    assert not r.res[6][0] and 'MISMATCH' not in r.res[6][1]


def test_psana_check_failure_fails(tmp_path, monkeypatch):
    r, seen = finish_with(tmp_path, monkeypatch, checks="FAIL ['event 1: w3 0x2a2a != seed 0x1234']",
                          edit_seed=0x2a2a, expect_seed=0x1234)
    assert seen['seed'] == 0x1234 and not r.res[6][0]


def test_expected_seed_order(tmp_path):
    assert run(tmp_path).seed == 0x1234
    assert run(tmp_path, edit_seed=0x2a2a).seed == 0x2a2a
    assert run(tmp_path, edit_seed=0x2a2a, expect_seed=0x1234).seed == 0x1234


# ---------------- assertion 7 ----------------

READ = {'path': '/ws/configDB/get_configuration/tst/BEAM/fakecam_0/', 'success': True}
SAVE = {'path': '/ws/configDB/modify_device/tst/BEAM/', 'success': True}


def line(seed, pid=4242, src='configdb BEAM/fakecam_0'):
    return 'tst-drp[%d]: <I> Sim payload seed %d (0x%08x) from %s' % (pid, seed, seed, src)


def cfg(seed=0x2a2a, **kw):
    c = {'window': (0.0, 1.0), 'reads': [READ], 'seed_lines': [line(seed)], 'page_cfg_reqs': [], 'drp_pid': 4242,
         'saves': [SAVE], 'edit_ok': True, 'edit_status': 'saved BEAM/fakecam_0 in tst: new key 3', 'own_seed': seed}
    c.update(kw)
    return c


def check7(tmp_path, c, **kw):
    r = run(tmp_path, **kw)
    r.cfg = c
    ok = r.check_config()
    print(r.res[7][1])
    return ok


def test_config_read_pass(tmp_path):
    assert check7(tmp_path, cfg(), edit_seed=0x2a2a)
    assert check7(tmp_path, cfg(0x1234, saves=[], own_seed=None))          # no edit: up's seed


@pytest.mark.parametrize('change', [
    {'reads': []},                                               # the DRP did not read the config DB
    {'reads': [dict(READ, success=False)]},
    {'seed_lines': []},                                          # no DRP log line at that Configure
    {'seed_lines': [line(0x2a2a), line(0x2a2a)]},                # two Configures in the window
    {'seed_lines': [line(0x2a2a, src='kwarg sim_seed')]},        # not from the config DB
    {'seed_lines': [line(0x2a2a, pid=1)]},                       # not the DRP's pid
    {'page_cfg_reqs': [[0.5, 'fetch', '/api/configdb/config?alias=BEAM&device=fakecam_0']]},
    {'saves': []},                                               # the editor did not save
    {'edit_ok': False},
    {'edit_status': 'NOT applied'},
    {'own_seed': 0x1234},                                        # the store does not hold the edit
])
def test_config_read_fails(tmp_path, change):
    assert not check7(tmp_path, cfg(**change), edit_seed=0x2a2a)


def test_edit_one_value_expect_another_fails(tmp_path):
    assert not check7(tmp_path, cfg(0x2a2a), edit_seed=0x2a2a, expect_seed=0x1234)


def test_no_configure_window(tmp_path):
    r = run(tmp_path)
    assert not r.check_config() and 'not reached' in r.res[7][1]


# ---------------- logs ----------------

def test_lines_after_and_access_records(tmp_path):
    p = tmp_path / 'a.jsonl'
    p.write_text(json.dumps({'path': '/x/'}) + '\n')
    off = e2e.fsize(str(p))
    with open(p, 'a') as f:
        f.write(json.dumps(READ) + '\nnot json\n' + json.dumps(SAVE) + '\n{"partial": ')
    recs = e2e.access_records(str(p), off)
    assert recs == [READ, SAVE]
    assert e2e.lines_after(str(tmp_path / 'missing'), 0) == [] and e2e.fsize(None) == 0


# ---------------- --break truncate-xtc2 ----------------

def dgram(service, payload=b''):
    return struct.pack('<QI', 0, service << 24) + struct.pack('<IHHI', 0, 0, 0, 12 + len(payload)) + payload


def write_run(tmp_path, n_l1=150, slow_after=120):
    d = tmp_path / 'data' / 'tst' / 'tstx00001' / 'xtc'
    d.mkdir(parents=True)
    body = [dgram(2, b'c' * 40), dgram(4), dgram(6), dgram(8)]
    for i in range(1, n_l1 + 1):
        body.append(dgram(12, struct.pack('<I', i) * 4))
        if i == slow_after:
            body.append(dgram(10, b's' * 8))
    body += [dgram(9), dgram(7), dgram(5)]
    p = d / 'tstx00001-r0001-s000-c000.xtc2'
    p.write_bytes(b''.join(body))
    p.chmod(0o444)                              # as the DRP's file writer leaves it
    return p


def test_truncate_xtc2(tmp_path):
    p = write_run(tmp_path)
    before = e2e.xtc2_dgrams(str(p))
    assert [d[2] for d in before].count(12) == 150 and len(before) == 158
    size = p.stat().st_size
    text = e2e.truncate_xtc2(ds.Work(str(tmp_path)), 'tstx00001', 1, drop=100)
    after = e2e.xtc2_dgrams(str(p))
    assert [d[2] for d in after].count(12) == 50
    assert [d[2] for d in after][:4] == [2, 4, 6, 8] and after[-1][2] == 12
    assert sum(d[1] for d in after) == p.stat().st_size            # cut at a datagram boundary
    assert p.stat().st_mode & 0o777 == 0o444                       # mode kept
    assert (tmp_path / 'data/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2.untruncated').stat().st_size == size
    assert 'dropped the last 100 L1Accepts and 4 other datagrams' in text, text
    assert 'SlowUpdate, Disable, EndStep, EndRun' in text and 'kept 50 L1Accepts' in text


def test_truncate_too_short_and_missing(tmp_path):
    p = write_run(tmp_path, n_l1=80, slow_after=0)
    size = p.stat().st_size
    assert 'not cut' in e2e.truncate_xtc2(ds.Work(str(tmp_path)), 'tstx00001', 1, drop=100)
    assert p.stat().st_size == size
    assert 'no file matching' in e2e.truncate_xtc2(ds.Work(str(tmp_path)), 'tstx00001', 2)
