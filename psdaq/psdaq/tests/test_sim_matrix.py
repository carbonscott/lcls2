"""daq_sim matrix without a DAQ: which types it runs, the assertions it reads from a cycle's
record (a passing run and the three deliberate breaks as their records look), the node lock,
the features it cannot run yet, the summary's verdicts and the --only coverage command."""

import argparse
import json
import os
import subprocess
import sys
import time

import pytest

from psdaq.sim import coverage, daq_sim, matrix

REPO = coverage.find_repo(os.path.dirname(os.path.abspath(__file__)))


def args(**kw):
    p = argparse.ArgumentParser()
    p.add_argument('-w', '--workdir', default='daq_sim_work')
    matrix.add_arguments(p)
    a = p.parse_args([])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


# --- what runs --------------------------------------------------------------------------------

def test_types_are_the_run_rows_in_factory_order_then_the_other_sim_types():
    got, cannot = matrix.run_types(REPO)
    names = [t for t, _ in got]
    rows, _ = coverage.enumerate_rows(REPO)
    status = json.load(open(os.path.join(REPO, coverage.STATUS_FILE)))
    run = [r.split(':')[2] for r in rows if r.startswith('det:drp:') and status.get(r, {}).get('status') == 'RUN']
    assert names[:len(run)] == run                      # factory order
    assert set(names) == set(run) | set(daq_sim.SIM_TYPES) and len(names) == len(set(names))
    assert all(t in daq_sim.SIM_TYPES for t in names) and cannot == []


def test_a_run_row_the_matrix_cannot_run_is_reported(tmp_path):
    rows, _ = coverage.enumerate_rows(REPO)
    gpu = next(r for r in rows if r.startswith('det:drp_gpu:'))
    status = json.load(open(os.path.join(REPO, coverage.STATUS_FILE)))
    status[gpu] = {'status': 'RUN'}
    path = tmp_path / 'status.json'
    path.write_text(json.dumps(status))
    got, cannot = matrix.run_types(REPO, str(path))
    assert cannot == [gpu] and (gpu.split(':')[2], gpu) not in got


def test_features_not_in_psdaq_sim_feature_are_not_available(tmp_path):
    from psdaq.sim import feature
    assert set(matrix.available_features()) == set(feature.FEATURES) <= set(matrix.FEATURES)
    missing = [x for x in matrix.FEATURES if x not in feature.FEATURES]
    for x in missing:                                   # returns before any DAQ
        r = matrix.run_feature(args(), x, str(tmp_path / x), dict(os.environ))
        assert r['pass'] is False and r['verdict'] == 'NOT AVAILABLE'
        assert r['assertions'] == [{'name': f'features/{x}', 'ok': False,
                                    'detail': f'NOT AVAILABLE: psdaq.sim.feature runs {",".join(feature.FEATURES)}'}]


# --- assertions from a cycle's record -----------------------------------------------------------

ROWS = [['t0', 't1', s, s, None] for s in ('unallocated', 'allocated', 'connected', 'configured',
                                           'starting', 'paused', 'running')] + \
       [['t0', 't1', s, s, None] for s in ('paused', 'starting', 'configured', 'connected', 'allocated',
                                           'unallocated', 'reset')]
COUNTS = {'simxpm NumL0Acc': 1018, 'TEB_WrtCt': 1018, 'psana2 events': 1018, 'psana2 with data': 1018,
          'psana2 checks': 'PASS', 'xtc2 file': '/w/data/tst/x/xtc/x-r0001-s000-c000.xtc2 (1 B)'}
EVIDENCE = ['2026-11-09T05:00:00.000-08:00 evidence 20261109T0500-cycle-abc-1: det:drp:fakecam prog:control '
            'prog:drp prog:pyxpm prog:teb']


def record(**kw):
    rec = {'transitions': [list(r) for r in ROWS], 'messages': [], 'counts': dict(COUNTS), 'ok': True,
           'start': 'reset', 'final': 'reset', 'experiment': 'tstx00001', 'run': 1}
    rec.update(kw)
    return rec


def checks(rec, out=EVIDENCE, det='fakecam', wd='/nonexistent', events=1000, programs=False):
    res, got = {'cycle exit': 0}, {}
    matrix.type_checks(res, det, wd, rec, out, events,
                       lambda what, ok, detail: got.__setitem__(what, (ok, detail)), programs=programs)
    return res, got


def test_a_passing_cycle_passes_every_assertion():
    res, got = checks(record())
    assert {k: v[0] for k, v in got.items()} == {'transitions': True, 'counts': True, 'per-event': True,
                                                'evidence': True}
    assert res['daq'] == res['psana2'] == res['with_data'] == 1018 and res['per_event'] == 'PASS'
    assert res['evidence'] == '20261109T0500-cycle-abc-1' and res['run_id'] == 'tstx00001/r0001'
    line = matrix.type_line(dict(res, type='fakecam', node='n1', job='42', **{'pass': True}))
    assert line.startswith('TYPE fakecam ') and 'node n1 job 42 run /w/data/tst/x/xtc/x-r0001-s000-c000.xtc2 ' \
        'DAQ 1018 psana2 1018 with-data 1018 per-event PASS PASS' in line


def test_register_fault_fails_transitions_and_names_the_register(tmp_path):
    """--break register: Configure fails; the detail carries the error and the DRP log's FAULT."""
    log = tmp_path / 'pmlogs' / 'x' / 'y'
    log.mkdir(parents=True)
    (log / '05_00_00_host:epix100_0.log').write_text(
        'noise\nFAULT ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay @mem+0x10 reads back 0x0\n'
        'pyrogue: Verify error for block ...DaqTriggerDelay\n')
    rows = [list(r) for r in ROWS[:3]] + [['t0', 't1', 'configured', 'connected', 'configure failed']]
    counts = {'simxpm NumL0Acc': 0, 'TEB_EvtCt': 0}
    res, got = checks(record(transitions=rows, final='connected', counts=counts, ok=False,
                             messages=[['t', 'error', 'epix100_0: configure failed']]),
                      out=[], det='epix100', wd=str(tmp_path))
    ok, detail = got['transitions']
    assert not ok and 'setState configured -> connected (error: configure failed)' in detail
    assert 'status stream error: epix100_0: configure failed' in detail and 'never reached running' in detail
    assert 'epix100_0 log: FAULT ePixBoard.ePix100aFPGA.EpixFpgaRegisters.DaqTriggerDelay' in detail
    assert not got['counts'][0] and not got['per-event'][0] and not got['evidence'][0]


def test_killed_drp_fails_transitions_and_counts():
    """--break kill-drp: Disable never completes and the TEB and the file fall short of simxpm."""
    rows = [list(r) for r in ROWS[:7]] + [['t0', 't1', 'paused', 'running', 'timed out']]
    counts = dict(COUNTS, **{'TEB_WrtCt': 310, 'psana2 events': 301, 'psana2 with data': 301})
    res, got = checks(record(transitions=rows, final='running', counts=counts, ok=False), out=[])
    assert not got['transitions'][0] and 'setState paused -> running (error: timed out)' in got['transitions'][1]
    assert 'ended in \'running\', started in \'reset\'' in got['transitions'][1]
    assert not got['counts'][0] and 'TEB_WrtCt 310, psana2 events 301' in got['counts'][1]


def test_corrupt_payload_fails_only_the_per_event_check_and_evidence():
    """--break corrupt: every count agrees; only xtc2_check's per-event compare sees the byte."""
    bad = "FAIL ['event 500: payload pattern broken: 1 of 60 payload words differ, first lane 0 w32 0x1 != 0xfe']"
    res, got = checks(record(counts=dict(COUNTS, **{'psana2 checks': bad}), ok=False), out=[])
    assert got['transitions'][0] and got['counts'][0]
    assert not got['per-event'][0] and 'event 500: payload pattern broken' in got['per-event'][1]
    assert not got['evidence'][0] and '(the cycle failed)' in got['evidence'][1]


def test_evidence_rejected_by_coverage_fails():
    out = EVIDENCE + ['2026-11-09T05:00:00.000-08:00 evidence 20261109T0500-cycle-abc-1: coverage would reject '
                      'it for det:drp:fakecam: recorded with tracked files modified']
    res, got = checks(record(), out=out)
    assert not got['evidence'][0] and 'recorded with tracked files modified' in got['evidence'][1]


def test_the_programs_run_needs_every_program_check_and_all_its_evidence():
    counts = dict(COUNTS, **{k: 'PASS' for k in matrix.PROGRAM_CHECKS}, MEB_EvtCt=1018)
    counts['ami shot'] = 'PASS (viewer showed the run)'
    res, got = checks(record(counts=counts), programs=True)
    assert got['checks'][0] and 'ami check: PASS' in got['checks'][1] and 'MEB_EvtCt 1018' in got['checks'][1]
    assert got['evidence'][0] and 'for 5 rows' in got['evidence'][1]
    del counts['gui witness']
    res, got = checks(record(counts=counts), programs=True)
    assert not got['checks'][0] and 'gui witness: did not run' in got['checks'][1]
    counts['gui witness'] = 'FAIL groupca read nothing'
    res, got = checks(record(counts=counts, ok=False), programs=True)
    assert not got['checks'][0]
    out = EVIDENCE + ['2026-11-09T05:00:00.000-08:00 evidence 20261109T0500-cycle-abc-1: coverage would reject '
                      'it for prog:ami-client: its log of ami-client gives no pid']
    counts['gui witness'] = 'PASS'
    res, got = checks(record(counts=counts), out=out, programs=True)
    assert not got['evidence'][0] and 'prog:ami-client' in got['evidence'][1]      # any row, not only det
    res, got = checks(record(counts=counts), out=out)
    assert got['evidence'][0]                           # a type's run needs only its det row


def test_no_record_fails_every_cycle_assertion():
    res, got = checks(None)
    assert set(got) == {'transitions', 'counts', 'per-event', 'evidence'} and not any(v[0] for v in got.values())


# --- the lock ---------------------------------------------------------------------------------

def test_lock_is_flock_and_waits(tmp_path):
    path = str(tmp_path / 'node.lock')
    with matrix.Lock(path, 5):
        r = subprocess.run(['flock', '-n', path, 'true'])     # flock(1) sees it taken
        assert r.returncode == 1
        with pytest.raises(daq_sim.Fail, match='not free after 0 s'):
            with matrix.Lock(path, 0):
                pass
    assert subprocess.run(['flock', '-n', path, 'true']).returncode == 0
    with matrix.Lock(None, 0):                          # no lock file: nothing to take
        pass


def test_lock_waits_in_the_queue_and_times_out(tmp_path):
    """Held by flock(1) for 2 s: the Lock blocks (no polling) and gets it at the hand-over; held
    longer than the timeout: Fail after it."""
    path = str(tmp_path / 'node.lock')
    holder = subprocess.Popen(['flock', path, 'sleep', '2'])
    time.sleep(0.5)
    t0 = time.monotonic()
    with matrix.Lock(path, 30):
        waited = time.monotonic() - t0
    holder.wait()
    assert 1.0 < waited < 10
    holder = subprocess.Popen(['flock', path, 'sleep', '5'])
    time.sleep(0.5)
    t0 = time.monotonic()
    with pytest.raises(daq_sim.Fail, match='not free after 1 s'):
        with matrix.Lock(path, 1):
            pass
    assert time.monotonic() - t0 < 3
    holder.wait()


# --- the summary ------------------------------------------------------------------------------

def result(name, ok, ended='2026-11-09T05:00:00'):
    return {'assertions': [{'name': name, 'ok': ok, 'detail': 'x'}], 'ended': ended, 'pass': ok}


def test_merge_carries_results_of_the_same_head_only(tmp_path):
    path = str(tmp_path / 's.json')
    first = matrix.merge(path, 'abc', None, {'types': {'fakecam': result('types/fakecam/up', True)},
                                              'features': {}, 'coverage': None,
                                              'programs': result('programs/up', True)})
    json.dump(first, open(path, 'w'))
    again = matrix.merge(path, 'abc', None, {'types': {'epix100': result('types/epix100/up', True)},
                                              'features': {}, 'coverage': None})
    assert again['types']['fakecam']['carried'] and not again['types']['epix100']['carried']
    assert again['programs']['carried']
    other = matrix.merge(path, 'def', None, {'types': {}, 'features': {}, 'coverage': None})
    assert other['types'] == {}
    broken = matrix.merge(path, 'abc', 'corrupt', {'types': {}, 'features': {}, 'coverage': None})
    assert broken['types'] == {}


def test_whole_verdict_needs_every_section_and_a_fresh_coverage():
    s = {'types': {'fakecam': result('types/fakecam/up', True, '2026-11-09T05:00:00')},
         'features': {x: result(f'features/{x}', True) for x in matrix.FEATURES},
         'programs': None, 'coverage': dict(result('coverage', True), started='2026-11-09T06:00:00')}
    w = matrix.whole_verdict(s, ['fakecam'], [])
    assert not w['pass'] and w['missing'] == ['programs']
    s['programs'] = result('programs/up', True)
    assert matrix.whole_verdict(s, ['fakecam'], [])['pass']
    w = matrix.whole_verdict(s, ['fakecam', 'epix100'], [])
    assert not w['pass'] and w['missing'] == ['types/epix100']
    s['types']['fakecam']['ended'] = '2026-11-09T07:00:00'
    w = matrix.whole_verdict(s, ['fakecam'], [])
    assert not w['pass'] and 'coverage ran at' in w['stale']
    s['coverage']['started'] = '2026-11-09T08:00:00'
    s['features']['c'] = result('features/c', False)
    assert matrix.whole_verdict(s, ['fakecam'], [])['failed'] == ['features/c']
    assert matrix.whole_verdict(s, ['fakecam'], ['det:drp_gpu:x'])['failed'][-1] == 'types/det:drp_gpu:x/runnable'


def test_summary_exit_names_the_failed_assertion(capsys):
    results = {'types': {}, 'programs': None,
               'features': {'c': dict(result('features/c', False), verdict='NOT AVAILABLE')},
               'coverage': {'assertions': [{'name': 'coverage', 'ok': True, 'detail': '78 rows'}]}, 'extra': []}
    rc = matrix.print_summary('abc', 0, 't0', results, '/s.json', None, None, '')
    out = capsys.readouterr().out
    assert rc == 1 and 'FAILED features/c: x' in out and out.rstrip().endswith('MATRIX FAIL (1 of 2 assertions failed)')
    results['features'] = {}
    assert matrix.print_summary('abc', 0, 't0', results, '/s.json', None, None, '') == 0
    assert capsys.readouterr().out.rstrip().endswith('MATRIX PASS (1 assertions)')


def test_breaks_and_sections_are_checked(tmp_path):
    with pytest.raises(daq_sim.Fail, match='--only nope'):
        matrix.cmd_matrix(args(only=['nope'], workdir=str(tmp_path)))
    with pytest.raises(daq_sim.Fail, match='--break runs the types section only'):
        matrix.cmd_matrix(args(only=['coverage'], breakage='kill-drp', workdir=str(tmp_path)))
    assert set(matrix.BREAK_TYPES) == set(matrix.BREAKS)
    assert matrix.BREAK_TYPES['register'] in matrix.FAULTS


def test_drp_pid():
    me = os.getpid()
    assert daq_sim.drp_pid({'procs': {'x_0': me}}, 'x_0') == (me, daq_sim.cmdline(me))
    assert daq_sim.drp_pid({'procs': {}}, 'x_0') == (None, '')
    p = subprocess.Popen(['sleep', '0'])
    p.wait()
    assert daq_sim.drp_pid({'procs': {'x_0': p.pid}}, 'x_0') == (None, '')


def test_cycle_takes_kill_drp_and_matrix_its_options():
    r = subprocess.run([sys.executable, '-m', 'psdaq.sim.daq_sim', 'cycle', '--help'], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0 and '--kill-drp' in r.stdout
    r = subprocess.run([sys.executable, '-m', 'psdaq.sim.daq_sim', 'matrix', '--help'], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0 and all(o in r.stdout for o in ('--only', '--types', '--break', '--lock'))


# --- the command, coverage only -----------------------------------------------------------------

def test_only_coverage_writes_the_summary(tmp_path):
    env = dict(os.environ)
    env.pop('SIM_ENV_SOURCED', None)
    status = tmp_path / 'status.json'
    status.write_text('{}')
    cmd = [sys.executable, '-m', 'psdaq.sim.daq_sim', 'matrix', '--only', 'coverage', '-w', str(tmp_path / 'w'),
           '--repo', REPO, '--status', str(status), '--evidence', str(tmp_path / 'ev')]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    assert r.returncode == 1, r.stdout[-2000:] + r.stderr[-2000:]
    assert 'FAILED coverage: at ' in r.stdout and r.stdout.rstrip().endswith('MATRIX FAIL (1 of 1 assertions failed)')
    s = json.load(open(tmp_path / 'w' / 'matrix-summary.json'))
    assert s['exit'] == 1 and s['coverage']['pass'] is False and s['assertions'][0]['name'] == 'coverage'
    assert not s['whole']['pass'] and 'features/a' in s['whole']['missing']
