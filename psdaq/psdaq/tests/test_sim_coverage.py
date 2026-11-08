"""Tests for the DAQ coverage check (psdaq.sim.coverage, 'daq_sim coverage').

They run on the checkout that holds this file: the rows are enumerated from its source and
the evidence must carry its HEAD.  Status files and evidence go to tmp dirs.
"""

import io
import json
import os
import re
import subprocess
import sys

import pytest

from psdaq.sim import coverage

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = coverage.find_repo(HERE)
HEAD = coverage.head(REPO)


def run_check(status, evidence):
    """(exit code, output) of the check with this status file and evidence dir."""
    out = io.StringIO()
    res = coverage.check(REPO, str(status), str(evidence))
    coverage.report(res, file=out)
    return (0 if res['pass'] else 1), out.getvalue()


def all_rows():
    rows, problems = coverage.enumerate_rows(REPO)
    assert problems == []
    return rows


def write_daq_sim_cnf(path):
    """The .cnf daq_sim up writes, with placeholder values."""
    from psdaq.sim import daq_sim
    with open(path, 'w') as f:
        f.write(daq_sim.CNF.format(
            when='now', platform=5, alias='BEAM', instr='tst', xpm=0, pvbase='DAQ:SIM', trigger='tmoteb',
            slow=1, configdb='http://127.0.0.1:1/ws/configDB', lgbk='http://127.0.0.1:2/',
            activedet='/dev/null', ep=daq_sim.EP, prom='/tmp', det='fakecam', frames=3, data='/tmp',
            length=64, v=''))
    return path


def write_status(path, entries):
    path.write_text(json.dumps(entries))
    return path


def full_coverage(tmp_path):
    """A status file with every row RUN, and one evidence record at HEAD covering them all."""
    rows = all_rows()
    status = write_status(tmp_path / 'status.json', {r: {'status': 'RUN'} for r in rows})
    evidence = tmp_path / 'evidence'
    proof = tmp_path / 'run.log'
    proof.write_text('a run\n')
    coverage.record_evidence(list(rows), 'test', [str(proof)], repo=REPO, evidence=str(evidence))
    return rows, status, evidence, proof


# --- enumeration -------------------------------------------------------------------------

def test_detector_rows_match_an_independent_count():
    """One row per register_type call: compare with a plain line regex over each file."""
    rows = coverage.detector_rows(REPO)
    for exe, rel in coverage.DET_SOURCES:
        with open(os.path.join(REPO, rel)) as f:
            names = re.findall(r'^\s*f\.register_type\s*(?:<\w+>)?\s*\(\s*"(\w+)"', f.read(), re.M)
        mine = [r.split(':', 2)[2] for r in rows if r.startswith(f'det:{exe}:')]
        print(f'{rel}: regex {len(names)}, coverage {len(mine)}')
        assert names and mine == names


def test_program_rows_match_the_configs():
    """Every program a literal cmd string starts is a row, and every row's name is in a config."""
    rows = coverage.program_rows(REPO)[0]
    names = {r[len('prog:'):] for r in rows}
    texts = [re.sub(r'(?m)^\s*#.*$', '', open(p).read()) for p in coverage.config_files(REPO)]
    # the first word of each cmd value that is a plain string literal (no wrapper or interpreter)
    literal = re.compile(r'''\bcmd['"]?\s*:\s*f?['"](?:\w+=\S+\s+)*([\w./-]+)''')
    found = set()
    for text in texts:
        for word in literal.findall(text):
            if word not in coverage.WRAPPERS and not re.match(r'python[0-9.]*$', word):
                found.add(coverage.program_name(word))
    print(f'regex: {len(found)} programs started by literal cmds; coverage: {len(names)} rows')
    assert found and found <= names, sorted(found - names)
    absent = [n for n in names if not any(re.search(r'\b' + re.escape(n) + r'\b', t) for t in texts)]
    assert absent == []
    # alias rule, a branch not taken, a program named through a variable
    assert 'procstat.py' not in names and 'procstat' in names
    assert 'partca' in names and 'deadca' in names
    assert 'hpsBldCopy' in names and 'drp_gpu' in names


def test_resolve_wrappers():
    r = coverage.resolve
    assert r('taskset -c 4-63 drp -P tst -D ts')[0] == 'drp'
    assert r('taskset 0xffbfeffbfe drp_bld -P tmo')[0] == 'drp_bld'
    assert r('A=1 B=2 numactl -C 0-3 --membind=0 teb -P tst')[0] == 'teb'
    assert r('procServ --allow -n x -L log 29000 /usr/bin/control -P tst')[0] == 'control'
    assert r('/x/scripts/launch_py /x/scripts/deadca.py DAQ:LAB2 1 2')[0] == 'deadca'
    assert r('python -u -m psdaq.cas.partca DAQ:LAB2:PART:0')[0] == 'partca'
    assert r("bash -c 'nice -n 5 monReqServer -P tst'")[0] == 'monReqServer'
    assert r('/reg/g/pcds/dist/pds/tools/procmgr/procstat.py p1.cnf.last')[0] == 'procstat'
    assert coverage.detector_types(r('drp -l 0x1 -D ebeam,gmd -u x')[1]) == ['ebeam', 'gmd']


def test_config_rows_of_the_daq_sim_cnf(tmp_path):
    """The rows daq_sim cycle records come from the .cnf daq_sim up writes."""
    cnf = write_daq_sim_cnf(str(tmp_path / 'daq_sim.cnf'))
    assert sorted(coverage.config_rows(cnf)) == ['det:drp:fakecam', 'prog:control', 'prog:drp', 'prog:teb']
    assert coverage.stand_in_rows(['simxpm', 'configdb', 'lgbk'], repo=REPO) == ['prog:pyxpm']


def test_cycle_records_evidence_for_what_it_started(tmp_path, monkeypatch):
    """daq_sim cycle's evidence hook, on a work dir laid out as 'up' and a run leave it
    (no DAQ runs here); then the check accepts it for the seeded RUN/STAND-IN rows."""
    from psdaq.sim import daq_sim
    monkeypatch.setenv('DAQ_SIM_EVIDENCE', str(tmp_path / 'evidence'))
    work = daq_sim.Work(str(tmp_path / 'wd'))
    os.makedirs(work.dir)
    write_daq_sim_cnf(work.path('daq_sim.cnf'))
    xtc = work.path('data', 'tst', 'tstx00001', 'xtc', 'tstx00001-r0001-s000-c000.xtc2')
    files = [xtc, work.path('logs', 'cycle.jsonl')] + \
        [work.path('logs', n + '.log') for n in ('configdb', 'lgbk', 'simxpm')] + \
        [work.path('pmlogs', '2026', '11', f'08_12:00:00_node:{p}.log') for p in daq_sim.PROCS]
    for f in files:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, 'w').close()
    state = {'cnf': 'daq_sim.cnf',
             'services': {n: {'pid': 1, 'log': work.path('logs', n + '.log')} for n in ('configdb', 'lgbk', 'simxpm')}}
    daq_sim._record_cycle_evidence(work, state, 'tstx00001', 1, {'psana2 events': 1000}, 'start')
    names = os.listdir(tmp_path / 'evidence')
    assert len(names) == 1
    record = json.load(open(tmp_path / 'evidence' / names[0]))
    assert record['sha'] == HEAD and record['kind'] == 'cycle' and record['run_id'] == 'tstx00001/r0001'
    assert record['rows'] == ['det:drp:fakecam', 'prog:control', 'prog:drp', 'prog:pyxpm', 'prog:teb']
    assert sorted(record['files']) == sorted(files + [work.path('daq_sim.cnf')])
    code, out = run_check(os.path.join(REPO, coverage.STATUS_FILE), tmp_path / 'evidence')
    for row in record['rows']:
        line = [l for l in out.splitlines() if l.startswith(row + ' ')][0]
        print(line)
        assert f'evidence {names[0][:-5]}' in line
    assert 'FAIL: 0 error(s), 0 RUN/STAND-IN row(s) without valid evidence,' in out


# --- status and evidence -----------------------------------------------------------------

def test_full_coverage_passes(tmp_path):
    rows, status, evidence, _ = full_coverage(tmp_path)
    code, out = run_check(status, evidence)
    print(out[-300:])
    assert code == 0
    assert f'{len(rows)} rows, {len(rows)} run, 0 stand-in, 0 N/A, 0 unproven' in out
    assert out.rstrip().endswith('PASS')


def test_evidence_at_another_sha_is_rejected_naming_the_row(tmp_path):
    rows, status, evidence, proof = full_coverage(tmp_path)
    path = coverage.record_evidence(['det:drp:fakecam'], 'test', [str(proof)], repo=REPO,
                                    evidence=str(evidence))
    for name in os.listdir(evidence):                 # keep only the fakecam record, at a wrong SHA
        if os.path.join(evidence, name) != path:
            os.remove(os.path.join(evidence, name))
    record = json.load(open(path))
    record['sha'] = 'f' * 40 if HEAD != 'f' * 40 else '0' * 40
    json.dump(record, open(path, 'w'))
    code, out = run_check(status, evidence)
    line = [l for l in out.splitlines() if l.startswith('det:drp:fakecam ')][0]
    print(line)
    assert code == 1
    assert 'NO VALID EVIDENCE' in line and f'recorded at {record["sha"][:9]}, not at HEAD {HEAD[:9]}' in line
    assert '  det:drp:fakecam: RUN row without valid evidence' in out


def test_removing_one_rows_evidence_fails_naming_it(tmp_path):
    rows, status, evidence, proof = full_coverage(tmp_path)
    for name in os.listdir(evidence):
        os.remove(os.path.join(evidence, name))
    rest = [r for r in rows if r != 'det:drp:fakecam']
    coverage.record_evidence(rest, 'test', [str(proof)], repo=REPO, evidence=str(evidence))
    code, out = run_check(status, evidence)
    fails = [l for l in out.splitlines() if l.startswith('  ') and 'without valid evidence' in l]
    print('\n'.join(fails))
    assert code == 1
    assert fails == [f'  det:drp:fakecam: RUN row without valid evidence at HEAD {HEAD[:9]}']


def test_missing_evidence_file_is_rejected(tmp_path):
    rows, status, evidence, proof = full_coverage(tmp_path)
    proof.unlink()
    code, out = run_check(status, evidence)
    assert code == 1 and 'files missing' in out


def test_unknown_row_in_status_file_fails(tmp_path):
    rows, status, evidence, _ = full_coverage(tmp_path)
    entries = json.loads(status.read_text())
    entries['det:drp:nosuchtype'] = {'status': 'RUN'}
    write_status(status, entries)
    code, out = run_check(status, evidence)
    print([l for l in out.splitlines() if 'nosuchtype' in l])
    assert code == 1
    assert 'ERROR det:drp:nosuchtype: in the status file, but the enumeration does not find it' in out


def test_bad_status_entries_fail(tmp_path):
    rows, status, evidence, _ = full_coverage(tmp_path)
    entries = json.loads(status.read_text())
    entries['prog:pyxpm'] = {'status': 'STAND-IN', 'stand_in': 'simxpm'}          # no interface
    entries['prog:qRead'] = {'status': 'N/A'}                                     # no reason
    entries['prog:teb'] = {'status': 'DONE'}
    write_status(status, entries)
    code, out = run_check(status, evidence)
    assert code == 1
    assert 'prog:pyxpm: STAND-IN needs interface' in out
    assert 'prog:qRead: N/A needs reason' in out
    assert 'prog:teb: status must be one of' in out


def test_rows_without_status_are_unproven(tmp_path):
    rows, status, evidence, _ = full_coverage(tmp_path)
    write_status(status, {})
    code, out = run_check(status, evidence)
    assert code == 1
    assert f'{len(rows)} rows, 0 run, 0 stand-in, 0 N/A, {len(rows)} unproven' in out


# --- the commands --------------------------------------------------------------------------

@pytest.mark.parametrize('argv', [['-m', 'psdaq.sim.coverage'], ['-m', 'psdaq.sim.daq_sim', 'coverage'],
                                  ['-m', 'psdaq.sim.daq_sim', 'matrix']])
def test_commands_return_the_verdict(tmp_path, argv):
    rows, status, evidence, proof = full_coverage(tmp_path)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(REPO, 'psdaq')] + sys.path))
    env.pop('SIM_ENV_SOURCED', None)
    cmd = [sys.executable] + argv + ['--repo', REPO, '--status', str(status), '--evidence', str(evidence)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert r.stdout.rstrip().endswith('PASS')
    proof.unlink()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 1 and 'FAIL' in r.stdout
