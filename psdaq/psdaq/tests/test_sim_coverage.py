"""Tests for the DAQ coverage check (psdaq.sim.coverage, 'daq_sim coverage').

They run on the checkout that holds this file: the rows are enumerated from its source and
the evidence must carry its HEAD.  Status files and evidence go to tmp dirs.
"""

import io
import json
import os
import re
import struct
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


def write_daq_sim_cnf(path, det='fakecam'):
    """The .cnf daq_sim up writes, with placeholder values."""
    from psdaq.sim import daq_sim
    with open(path, 'w') as f:
        f.write(daq_sim.CNF.format(
            when='now', platform=5, alias='BEAM', instr='tst', xpm=0, pvbase='DAQ:SIM', trigger='tmoteb',
            slow=1, configdb='http://127.0.0.1:1/ws/configDB', lgbk='http://127.0.0.1:2/',
            activedet='/dev/null', ep=daq_sim.EP, prom='/tmp', det=det, frames=3, data='/tmp',
            length=64, v='', segments='',
            simk=daq_sim.SIM_TYPES[det]['kwargs'].format(length=64, seed=0x1234)))
    return path


def write_xtc2(path, events=2):
    """A minimal xtc2 file: a Configure and `events` L1Accepts, each an empty Parent Xtc."""
    with open(path, 'wb') as f:
        for service in [2] + [12] * events:
            f.write(struct.pack('<QIIHHI', 0, service << 24, 0, 0, 0, 12))
    return path


def record(rows, files, evidence, run_id='tstx00001/r0001', dirty=False):
    """An evidence record at HEAD, as a run from a clean checkout writes it (the tests also run
    in a tree with modified files, so 'dirty' is set here, not read from the tree)."""
    path = coverage.record_evidence(rows, 'test', [str(f) for f in files], run_id=run_id,
                                    repo=REPO, evidence=str(evidence))
    rec = json.load(open(path))
    rec['dirty'] = dirty
    json.dump(rec, open(path, 'w'))
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
    record(list(rows), [proof], evidence)
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


# The program rows at 2d9593bc5 and since (psdaq/psdaq/cnf unchanged), as an independent
# enumerator counted them in the first survey (.goal iteration 1, enum_programs.py: 52 started
# by the exec pass + 2 only in branches not taken; its 'python x.py' and 'procstat.py' entries
# named by the alias rule).  A cnf change must update this list; a dropped row fails here.
PINNED_PROGRAMS = frozenset('''
    ami-client ami-global ami-manager ami-node ami-worker bldcas cLoopTest control control_gui
    daqstat deadca drp drp_bld drp_gpu drp_pva drp_udpencoder dtica epicsArch epics_exporter
    groupca hpsBldCopy hpsBldServer hpsdbuscas hsd134PVs hsd64PVs hsdca hsdcas hsdpva hsdpvs
    lclsBldServer monReqServer partca procstat pvant pvatable pykcuxpm pyxpm qLoopTest qRead
    shmemClient sim_udpencoder teb tmo_acr_opal_feedback tprca tprcas tprioc tprtrig
    tpr_trigger wave8pvs xpmpva xpmpvas xpmPVs'''.split())


def program_row_diff(names):
    return {'dropped': sorted(PINNED_PROGRAMS - names), 'added': sorted(names - PINNED_PROGRAMS)}


def test_program_rows_are_the_pinned_independent_count():
    names = {r[len('prog:'):] for r in coverage.program_rows(REPO)[0]}
    print(f'pinned {len(PINNED_PROGRAMS)}, coverage {len(names)}: {program_row_diff(names)}')
    assert len(PINNED_PROGRAMS) == 52
    assert program_row_diff(names) == {'dropped': [], 'added': []}


def test_a_dropped_program_row_fails_the_pin(monkeypatch):
    """Without the launch_py wrapper rule, deadca and dtica (started only through launch_py in
    lab3-cam.cnf) would drop out of the enumeration; the pin names them."""
    wrappers = dict(coverage.WRAPPERS)
    del wrappers['launch_py']
    monkeypatch.setattr(coverage, 'WRAPPERS', wrappers)
    names = {r[len('prog:'):] for r in coverage.program_rows(REPO)[0]}
    diff = program_row_diff(names)
    print(diff)
    assert diff == {'dropped': ['deadca', 'dtica'], 'added': ['launch_py']}


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


@pytest.mark.parametrize('det', ['fakecam', 'epix100'])
def test_config_rows_of_the_daq_sim_cnf(tmp_path, det):
    """The rows daq_sim cycle records come from the .cnf daq_sim up writes (up --det <type>)."""
    cnf = write_daq_sim_cnf(str(tmp_path / 'daq_sim.cnf'), det)
    assert sorted(coverage.config_rows(cnf)) == [f'det:drp:{det}', 'prog:control', 'prog:drp', 'prog:teb']
    assert coverage.stand_in_rows(['simxpm', 'configdb', 'lgbk'], repo=REPO) == ['prog:pyxpm']


@pytest.mark.parametrize('det', ['fakecam', 'epix100'])
def test_cycle_records_evidence_for_what_it_started(tmp_path, monkeypatch, det):
    """daq_sim cycle's evidence hook, on a work dir laid out as 'up --det <type>' and a run
    leave it (no DAQ runs here); then the check accepts it for those rows.  The tree may have
    modified files while tests run, so the record is made as from a clean checkout."""
    from psdaq.sim import daq_sim
    monkeypatch.setenv('DAQ_SIM_EVIDENCE', str(tmp_path / 'evidence'))
    monkeypatch.setattr(coverage, 'dirty', lambda repo: False)
    monkeypatch.setattr(daq_sim, 'DETECTOR', daq_sim.DETECTOR)
    monkeypatch.setattr(daq_sim, 'PROCS', daq_sim.PROCS)
    daq_sim.use_det(det)
    work = daq_sim.Work(str(tmp_path / 'wd'))
    os.makedirs(work.dir)
    write_daq_sim_cnf(work.path('daq_sim.cnf'), det)
    xtc = work.path('data', 'tst', 'tstx00001', 'xtc', 'tstx00001-r0001-s000-c000.xtc2')
    files = [xtc, work.path('logs', 'cycle.jsonl')] + \
        [work.path('logs', n + '.log') for n in ('configdb', 'lgbk', 'simxpm')] + \
        [work.path('pmlogs', '2026', '11', f'08_12:00:00_node:{p}.log') for p in daq_sim.PROCS]
    for f in files:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, 'w').write('log\n')
    write_xtc2(xtc)
    assert f'08_12:00:00_node:{det}_0.log' in ' '.join(files)
    state = {'cnf': 'daq_sim.cnf', 'det': det,
             'services': {n: {'pid': 1, 'log': work.path('logs', n + '.log')} for n in ('configdb', 'lgbk', 'simxpm')}}
    daq_sim._record_cycle_evidence(work, state, 'tstx00001', 1, {'psana2 events': 1000}, 'start')
    names = os.listdir(tmp_path / 'evidence')
    assert len(names) == 1
    rec = json.load(open(tmp_path / 'evidence' / names[0]))
    assert rec['sha'] == HEAD and rec['kind'] == 'cycle' and rec['run_id'] == 'tstx00001/r0001'
    assert rec['dirty'] is False
    assert rec['rows'] == [f'det:drp:{det}', 'prog:control', 'prog:drp', 'prog:pyxpm', 'prog:teb']
    assert sorted(rec['files']) == sorted(files + [work.path('daq_sim.cnf')])
    entries = {r: {'status': 'RUN'} for r in rec['rows']}
    entries['prog:pyxpm'] = json.load(open(os.path.join(REPO, coverage.STATUS_FILE)))['prog:pyxpm']
    code, out = run_check(write_status(tmp_path / 'status.json', entries), tmp_path / 'evidence')
    for row in rec['rows']:
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
    path = record(['det:drp:fakecam'], [proof], evidence)
    for name in os.listdir(evidence):                 # keep only the fakecam record, at a wrong SHA
        if os.path.join(evidence, name) != path:
            os.remove(os.path.join(evidence, name))
    rec = json.load(open(path))
    rec['sha'] = 'f' * 40 if HEAD != 'f' * 40 else '0' * 40
    json.dump(rec, open(path, 'w'))
    code, out = run_check(status, evidence)
    line = [l for l in out.splitlines() if l.startswith('det:drp:fakecam ')][0]
    print(line)
    assert code == 1
    assert 'NO VALID EVIDENCE' in line and f'recorded at {rec["sha"][:9]}, not at HEAD {HEAD[:9]}' in line
    assert '  det:drp:fakecam: RUN row without valid evidence' in out


def test_removing_one_rows_evidence_fails_naming_it(tmp_path):
    rows, status, evidence, proof = full_coverage(tmp_path)
    for name in os.listdir(evidence):
        os.remove(os.path.join(evidence, name))
    rest = [r for r in rows if r != 'det:drp:fakecam']
    record(rest, [proof], evidence)
    code, out = run_check(status, evidence)
    fails = [l for l in out.splitlines() if l.startswith('  ') and 'without valid evidence' in l]
    print('\n'.join(fails))
    assert code == 1
    assert fails == [f'  det:drp:fakecam: RUN row without valid evidence at HEAD {HEAD[:9]}']


def test_missing_evidence_file_is_rejected(tmp_path):
    rows, status, evidence, proof = full_coverage(tmp_path)
    proof.unlink()
    code, out = run_check(status, evidence)
    assert code == 1 and '1 of 1 files missing' in out


def one_row_check(tmp_path, files, **kw):
    """(exit code, the det:drp:fakecam line, output) with only that row RUN and one record."""
    status = write_status(tmp_path / 'status.json', {'det:drp:fakecam': {'status': 'RUN'}})
    evidence = tmp_path / 'evidence'
    record(['det:drp:fakecam'], files, evidence, **kw)
    code, out = run_check(status, evidence)
    line = [l for l in out.splitlines() if l.startswith('det:drp:fakecam ')][0]
    print(line)
    return code, line, out


def test_record_from_a_dirty_tree_is_rejected(tmp_path):
    proof = tmp_path / 'run.log'
    proof.write_text('a run\n')
    code, line, out = one_row_check(tmp_path, [proof], dirty=True)
    assert code == 1
    assert 'NO VALID EVIDENCE' in line and 'recorded with tracked files modified' in line
    assert '  det:drp:fakecam: RUN row without valid evidence' in out


def test_record_without_a_run_id_is_rejected(tmp_path):
    proof = tmp_path / 'run.log'
    proof.write_text('a run\n')
    code, line, _ = one_row_check(tmp_path, [proof], run_id=None)
    assert code == 1 and 'names no run (run_id)' in line


def test_empty_evidence_file_is_rejected(tmp_path):
    proof, empty = tmp_path / 'run.log', tmp_path / 'empty.log'
    proof.write_text('a run\n')
    empty.write_text('')
    code, line, _ = one_row_check(tmp_path, [proof, empty])
    assert code == 1 and f'1 of 2 files empty, e.g. {empty}: empty' in line


@pytest.mark.parametrize('content,problem', [
    (b'not an xtc2 file, but long enough for a header', 'first datagram is transition'),
    (struct.pack('<QIIHHI', 0, 2 << 24, 0, 0, 0, 12) + struct.pack('<QIIHHI', 0, 12 << 24, 0, 0, 0, 40),
     'datagram 1 at byte 24: extent 40 does not fit the file (48 B)'),
    (struct.pack('<QIIHHI', 0, 2 << 24, 0, 0, 0, 12)[:20], 'header cut off'),
])
def test_xtc2_evidence_must_be_xtc2(tmp_path, content, problem):
    xtc = tmp_path / 'r0001.xtc2'
    xtc.write_bytes(content)
    code, line, _ = one_row_check(tmp_path, [xtc])
    assert code == 1 and 'not an xtc2 file' in line and problem in line


def test_a_valid_xtc2_file_counts(tmp_path):
    xtc = write_xtc2(str(tmp_path / 'r0001.xtc2'), events=3)
    assert coverage.xtc2_problem(xtc) is None
    code, line, _ = one_row_check(tmp_path, [xtc])
    assert 'evidence ' in line and 'NO VALID' not in line


def test_counts_are_rows_with_valid_evidence_not_claims(tmp_path):
    """R counts proven rows; the status file's claims are printed on their own line."""
    rows, status, evidence, proof = full_coverage(tmp_path)
    for name in os.listdir(evidence):
        os.remove(os.path.join(evidence, name))
    record(list(rows)[:10], [proof], evidence)
    code, out = run_check(status, evidence)
    print([l for l in out.splitlines() if 'rows,' in l or 'claims' in l])
    assert code == 1
    assert f'{len(rows)} rows, 10 run, 0 stand-in, 0 N/A, 0 unproven, {len(rows) - 10} claimed ' \
           'without valid evidence' in out
    assert f'status file claims (not counted above unless proven): {len(rows)} RUN, 0 STAND-IN, 0 N/A' in out


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
