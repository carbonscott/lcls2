"""Tests for the DAQ coverage check (psdaq.sim.coverage, 'daq_sim coverage').

They run on the checkout that holds this file: the rows are enumerated from its source and
the evidence must carry its HEAD.  Status files and evidence go to tmp dirs.
"""

import hashlib
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


# --- a run's files, laid out as the DAQ writes them -----------------------------------------

RUN_ID = 'tstx00001/r0001'
BEGINRUN = (1163038486, 825677369)      # sec, nsec of the BeginRun
BEGINRUN_TIME = '1163038486.825677369'  # as the TEB and simxpm log it
RUNINFO_SRC = 0x001                     # NamesId(0, 1)


def xtc(typeid, src, payload):
    return struct.pack('<IHHI', src, 0, typeid, 12 + len(payload)) + payload


def dgram(service, payload, stamp=0):
    return struct.pack('<QI', stamp, service << 24) + xtc(0, 0, payload)


def names(src, dettype, detname, alg, items):
    """A Names Xtc (xtcdata ShapesData.hh): NameInfo, then one Name per (name, type, rank)."""
    info = coverage.NAMEINFO.pack(sum(1 for i in items if i[2]), dettype.encode(), detname.encode(),
                                  b'detid', alg.encode(), 0x000001, 0)
    return xtc(4, src, info + b''.join(coverage.NAME.pack(b'', 0, n.encode(), t, r) for n, t, r in items))


def shapes_data(src, shapes, data):
    return xtc(1, src, (xtc(2, 0, b''.join(struct.pack('<5I', *s) for s in shapes)) if shapes else b'')
               + xtc(3, 0, data))


def write_run(path, dets, events=1000, run_id=RUN_ID, with_data=None):
    """An xtc2 file as a DRP writes a run: a Configure with the runinfo Names and one Names per
    detector (detType, detName); a BeginRun at BEGINRUN with the runinfo (experiment, run
    number); `events` L1Accepts, each with a ShapesData of every detector in with_data (default:
    all); an EndRun."""
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    expt, run = run_id.split('/r')
    srcs, cfg = {}, [names(RUNINFO_SRC, 'runinfo', 'runinfo', 'runinfo', [('expt', 10, 1), ('runnum', 2, 0)])]
    for i, (dettype, detname) in enumerate(dets):
        srcs[detname] = 0x100 + i       # NamesId(1, i)
        cfg.append(names(srcs[detname], dettype, detname, 'raw', [('value', 2, 0)]))
    e = expt.encode() + b'\0'
    e += b'\0' * (-len(e) % 4)
    l1 = b''.join(shapes_data(srcs[d], [], struct.pack('<I', 7))
                  for d in (srcs if with_data is None else with_data))
    with open(path, 'wb') as f:
        f.write(dgram(2, b''.join(cfg)))
        f.write(dgram(4, shapes_data(RUNINFO_SRC, [(len(e), 0, 0, 0, 0)], e + struct.pack('<I', int(run))),
                      stamp=BEGINRUN[0] << 32 | BEGINRUN[1]))
        f.write(b''.join(dgram(12, l1, stamp=l1_stamp(k)) for k in range(events)))
        f.write(dgram(5, b''))
    return path


def l1_stamp(k):
    """The timestamp of a test run's k-th L1Accept: 100 Hz from 1 s after its BeginRun."""
    return (BEGINRUN[0] + 1 + k // 100) << 32 | (k % 100) * 10000000


L1_FIRST, L1_LAST = coverage.stamp_seconds(l1_stamp(0)), coverage.stamp_seconds(l1_stamp(999))


def write_log(path, cmd, *lines):
    """A process's log as procmgr starts it: a header with its '# CMDLINE:', then its output."""
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(f'# ID:      x\n# PLATFORM:5\n# CMDLINE: {cmd}\n' + ''.join(l + '\n' for l in lines))
    return path


def run_files(d, rows, stand_ins=None):
    """The files of one run that proves `rows`: one xtc2 file with a detector of every det row's
    type; per drp executable a log that runs it with -D <those types> and names the xtc2 file;
    per program row a log that runs it (or its stand-in, {row: program}) and names the BeginRun
    time, as the TEB and simxpm log it."""
    types = {}
    for r in rows:
        if r.startswith('det:'):
            exe, t = r.split(':')[1:]
            types.setdefault(exe, []).append(t)
    xtc2 = write_run(os.path.join(d, 'tstx00001-r0001-s000-c000.xtc2'),
                     [(t, t) for t in sorted(set(sum(types.values(), [])))])
    files = [xtc2]
    for exe, ts in types.items():
        files.append(write_log(os.path.join(d, f'{exe}_0.log'), f'{exe} -P tst -D {",".join(ts)} -u {exe}_0',
                               f"Opening file '{xtc2}'"))
    ami = []
    for r in rows:
        if r.startswith('prog:'):
            name = (stand_ins or {}).get(r, r[len('prog:'):])
            cmd = f'python -m psdaq.sim.{name} -P DAQ:SIM' if name == 'simxpm' else f'{name} -p 5'
            if name in coverage.AMI_PROGRAMS:   # AMI's logs never name the run: its check does
                ami.append((name, ami_pid(name), f'{sys.executable} {d}/bin/{name} -p 31150 -H 127.0.0.1'))
                files.append(write_log(os.path.join(d, f'{name}.log'), f'{d}/bin/{name} -p 31150',
                                       f'@@@ The PID of new child "x:{name}.log" is: {ami[-1][1]}'))
                continue
            files.append(write_log(os.path.join(d, f'{name}.log'), cmd,
                                   f'EbAppBase  saw        BeginRun @ {BEGINRUN_TIME} (047325138ca92b)'))
    if ami:
        files.append(write_witness(os.path.join(d, 'ami_check.json'), ami_witness(xtc2, ami)))
    return files


def ami_pid(name):
    return 4000 + coverage.AMI_PROGRAMS.index(name)


def ami_witness(xtc2, served, run_id=RUN_ID, matches=None, **kw):
    """An ami_check witness as daq_sim cycle writes it: the run, AMI's per-event matches with
    psana2 and the AMI processes [(name, pid, cmdline)] that served the check."""
    w = {'witness': 'ami_check', 'run_id': run_id, 'xtc2': [xtc2], 'pass': True, 'problems': [],
         'matches': [[l1_stamp(k), k, 7] for k in range(5)] if matches is None else matches,
         'served_by': [{'pid': pid, 'cmdline': cmd} for _, pid, cmd in served]}
    w.update(kw)
    return w


def write_witness(path, w):
    with open(path, 'w') as f:
        json.dump(w, f)
    return path


def record(rows, files, evidence, run_id=RUN_ID, dirty=False, data_dir=None):
    """An evidence record at HEAD, as a run from a clean checkout writes it (the tests also run
    in a tree with modified files, so 'dirty' is set here, not read from the tree)."""
    path = coverage.record_evidence(rows, 'test', [str(f) for f in files], run_id=run_id,
                                    repo=REPO, evidence=str(evidence), data_dir=data_dir)
    rec = json.load(open(path))
    rec['dirty'] = dirty
    json.dump(rec, open(path, 'w'))
    return path


def write_status(path, entries):
    path.write_text(json.dumps(entries))
    return path


def full_coverage(tmp_path):
    """A status file with every row RUN, and one evidence record at HEAD covering them all,
    whose files are those of a run that proves them."""
    rows = all_rows()
    status = write_status(tmp_path / 'status.json', {r: {'status': 'RUN'} for r in rows})
    evidence = tmp_path / 'evidence'
    files = run_files(str(tmp_path / 'run'), list(rows))
    record(list(rows), files, evidence)
    return rows, status, evidence, files


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
    assert coverage.stand_in_rows(['simxpm', 'configdb', 'lgbk'], repo=REPO) == ['prog:pyxpm', 'prog:pykcuxpm']


@pytest.mark.parametrize('det', ['fakecam', 'epix100'])
def test_cycle_records_evidence_for_what_it_started(tmp_path, monkeypatch, capsys, det):
    """daq_sim cycle's evidence hook, on a work dir laid out as 'up --det <type>' and a run
    leave it (no DAQ runs here: the files are written as the DAQ writes them); then the check
    accepts it for those rows, and the hook says coverage rejects none of them.  The tree may
    have modified files while tests run, so the record is made as from a clean checkout."""
    from psdaq.sim import daq_sim
    monkeypatch.setenv('DAQ_SIM_EVIDENCE', str(tmp_path / 'evidence'))
    monkeypatch.setattr(coverage, 'dirty', lambda repo: False)
    monkeypatch.setattr(daq_sim, 'DETECTOR', daq_sim.DETECTOR)
    monkeypatch.setattr(daq_sim, 'PROCS', daq_sim.PROCS)
    daq_sim.use_det(det)
    work = daq_sim.Work(str(tmp_path / 'wd'))
    os.makedirs(os.path.join(work.dir, 'logs'))
    write_daq_sim_cnf(work.path('daq_sim.cnf'), det)
    xtc = write_run(work.path('data', 'tst', 'tstx00001', 'xtc', 'tstx00001-r0001-s000-c000.xtc2'), [(det, det)])
    services = {'configdb': 'configdb_server', 'lgbk': 'lgbk_server', 'simxpm': 'simxpm'}
    for name, module in services.items():           # as start_service heads them, then output
        with open(work.path('logs', name + '.log'), 'w') as f:
            f.write(daq_sim.log_header([sys.executable, '-m', f'psdaq.sim.{module}', '--port', '1']))
            f.write(f'simxpm INFO BeginRun rog 0x20 pulseId 0x1 time {BEGINRUN_TIME} to 1 link(s)\n'
                    if name == 'simxpm' else 'serving\n')
    with open(work.path('logs', 'cycle.jsonl'), 'w') as f:
        f.write('{}\n')
    cmds = {'control': ('control -v -C BEAM -P tst -u control -p 5',
                        f"recv_json(): {{'body': {{'absolute_path': '{xtc}'}}}}"),
            'teb0': ('teb -P tst -C localhost -u teb0 -p 5',
                     f'EbAppBase  saw        BeginRun @ {BEGINRUN_TIME} (047325138ca92b)'),
            f'{det}_0': (f'drp -P tst -C localhost -D {det} -d sim://127.0.0.1:3 -u {det}_0 -p 5',
                         f"Opening file '{xtc}'")}
    files = [xtc, work.path('logs', 'cycle.jsonl')] + [work.path('logs', n + '.log') for n in services]
    for p in daq_sim.PROCS:
        files.append(write_log(work.path('pmlogs', '2026', '11', f'08_12:00:00_node:{p}.log'), *cmds[p]))
    assert f'08_12:00:00_node:{det}_0.log' in ' '.join(files)
    state = {'cnf': 'daq_sim.cnf', 'det': det,
             'services': {n: {'pid': 1, 'log': work.path('logs', n + '.log')} for n in services}}
    daq_sim._record_cycle_evidence(work, state, 'tstx00001', 1, {'psana2 events': 1000}, 'start')
    printed = capsys.readouterr().out
    print(printed)
    assert 'evidence NOT recorded' not in printed and 'coverage would reject' not in printed
    names = os.listdir(tmp_path / 'evidence')
    assert len(names) == 1
    rec = json.load(open(tmp_path / 'evidence' / names[0]))
    assert rec['sha'] == HEAD and rec['kind'] == 'cycle' and rec['run_id'] == 'tstx00001/r0001'
    assert rec['dirty'] is False
    assert rec['rows'] == [f'det:drp:{det}', 'prog:control', 'prog:drp', 'prog:pykcuxpm', 'prog:pyxpm',
                           'prog:teb']
    assert sorted(rec['files']) == sorted(files + [work.path('daq_sim.cnf')])
    assert sorted(rec['content']) == sorted(rec['files'])
    assert rec['content'][xtc] == {'bytes': os.path.getsize(xtc),
                                   'sha256': hashlib.sha256(open(xtc, 'rb').read()).hexdigest()}
    entries = {r: {'status': 'RUN'} for r in rec['rows']}
    for r in ('prog:pyxpm', 'prog:pykcuxpm'):          # STAND-IN simxpm in the tree's status file
        entries[r] = json.load(open(os.path.join(REPO, coverage.STATUS_FILE)))[r]
    code, out = run_check(write_status(tmp_path / 'status.json', entries), tmp_path / 'evidence')
    for row in rec['rows']:
        line = line_of(out, row)
        print(line)
        assert f'evidence {names[0][:-5]}' in line
    assert 'FAIL: 0 error(s), 0 RUN/STAND-IN row(s) without valid evidence,' in out


def test_service_logs_are_headed_with_their_command(tmp_path):
    """start_service's header names the program, as coverage resolves it."""
    from psdaq.sim import daq_sim
    header = daq_sim.log_header(['/x/bin/python3', '-m', 'psdaq.sim.simxpm', '-P', 'DAQ:SIM'])
    assert header == '# CMDLINE: /x/bin/python3 -m psdaq.sim.simxpm -P DAQ:SIM\n'
    assert coverage.log_program('2026 starting\n' + header + 'more\n')[0] == 'simxpm'
    assert coverage.log_program('no header\n') == (None, [])


# --- status and evidence -----------------------------------------------------------------

def test_full_coverage_passes(tmp_path):
    rows, status, evidence, _ = full_coverage(tmp_path)
    code, out = run_check(status, evidence)
    print(out[-300:])
    assert code == 0
    assert f'{len(rows)} rows, {len(rows)} run, 0 stand-in, 0 N/A, 0 unproven' in out
    assert out.rstrip().endswith('PASS')


def test_evidence_at_another_sha_is_rejected_naming_the_row(tmp_path):
    rows, status, evidence, files = full_coverage(tmp_path)
    path = record(['det:drp:fakecam'], files, evidence)
    for name in os.listdir(evidence):                 # keep only the fakecam record, at a wrong SHA
        if os.path.join(evidence, name) != path:
            os.remove(os.path.join(evidence, name))
    rec = json.load(open(path))
    rec['sha'] = 'f' * 40 if HEAD != 'f' * 40 else '0' * 40
    json.dump(rec, open(path, 'w'))
    code, out = run_check(status, evidence)
    line = line_of(out, 'det:drp:fakecam')
    print(line)
    assert code == 1
    assert 'NO VALID EVIDENCE' in line and f'recorded at {rec["sha"][:9]}, not at HEAD {HEAD[:9]}' in line
    assert '  det:drp:fakecam: RUN row without valid evidence' in out


def test_removing_one_rows_evidence_fails_naming_it(tmp_path):
    rows, status, evidence, files = full_coverage(tmp_path)
    for name in os.listdir(evidence):
        os.remove(os.path.join(evidence, name))
    rest = [r for r in rows if r != 'det:drp:fakecam']
    record(rest, files, evidence)
    code, out = run_check(status, evidence)
    fails = [l for l in out.splitlines() if l.startswith('  ') and 'without valid evidence' in l]
    print('\n'.join(fails))
    assert code == 1
    assert fails == [f'  det:drp:fakecam: RUN row without valid evidence at HEAD {HEAD[:9]}']


def test_missing_evidence_file_is_rejected(tmp_path):
    rows, status, evidence, files = full_coverage(tmp_path)
    os.remove(files[-1])
    code, out = run_check(status, evidence)
    assert code == 1 and f'1 of {len(files)} files missing, e.g. {files[-1]}: missing' in out


def one_row_check(tmp_path, files, row='det:drp:fakecam', **kw):
    """(exit code, the row's line, output) with only that row RUN and one record."""
    status = write_status(tmp_path / 'status.json', {row: {'status': 'RUN'}})
    evidence = tmp_path / 'evidence'
    record([row], files, evidence, **kw)
    code, out = run_check(status, evidence)
    line = line_of(out, row)
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
    (struct.pack('<QIIHHI', 0, 2 << 24, 0, 0, 0, 24) + struct.pack('<IHHI', 0, 0, 4, 40),
     'datagram 0 at byte 0: Xtc at byte 24 has extent 40, beyond its parent'),
])
def test_xtc2_evidence_must_be_xtc2(tmp_path, content, problem):
    xtc = tmp_path / 'r0001.xtc2'
    xtc.write_bytes(content)
    code, line, _ = one_row_check(tmp_path, [xtc])
    assert code == 1 and '1 of 1 files not xtc2, e.g.' in line and 'not an xtc2 file' in line
    assert problem in line


def test_a_valid_run_proves_its_row(tmp_path):
    files = run_files(str(tmp_path / 'run'), ['det:drp:fakecam'])
    problem, content = coverage.xtc2_content(files[0])
    assert problem is None
    assert content['types'] == {'runinfo', 'fakecam'} and content['run'] == RUN_ID
    assert content['beginrun'] == BEGINRUN_TIME and content['l1accepts'] == 1000
    assert content['l1_with'] == {'fakecam': 1000}
    code, line, _ = one_row_check(tmp_path, files)
    assert 'evidence ' in line and 'NO VALID' not in line


def test_counts_are_rows_with_valid_evidence_not_claims(tmp_path):
    """R counts proven rows; the status file's claims are printed on their own line."""
    rows, status, evidence, files = full_coverage(tmp_path)
    for name in os.listdir(evidence):
        os.remove(os.path.join(evidence, name))
    record(list(rows)[:10], files, evidence)
    code, out = run_check(status, evidence)
    print([l for l in out.splitlines() if 'rows,' in l or 'claims' in l])
    assert code == 1
    assert f'{len(rows)} rows, 10 run, 0 stand-in, 0 N/A, 0 unproven, {len(rows) - 10} claimed ' \
           'without valid evidence' in out
    assert f'status file claims (not counted above unless proven): {len(rows)} RUN, 0 STAND-IN, 0 N/A' in out


# --- forged evidence: what the content of a record's files must show ----------------------

CYCLE_ROWS = ['prog:control', 'prog:drp', 'prog:pyxpm', 'prog:teb']
STAND_INS = {'prog:pyxpm': 'simxpm'}


def line_of(out, row):
    return [l for l in out.splitlines() if l.startswith(row + ' ')][0]


def cycle_runs(tmp_path, dets=('epix100', 'wave8', 'wave8he')):
    """A status file and one valid evidence record per 'daq_sim up --det <det>' + cycle run, each
    in its own dir: {det: (record path, its files)}."""
    os.makedirs(tmp_path, exist_ok=True)
    entries = {f'det:drp:{d}': {'status': 'RUN'} for d in dets}
    entries.update({r: {'status': 'RUN'} for r in CYCLE_ROWS})
    entries['prog:pyxpm'] = {'status': 'STAND-IN', 'stand_in': 'simxpm', 'interface': 'its PVs'}
    status = write_status(tmp_path / 'status.json', entries)
    runs = {}
    for d in dets:
        rows = [f'det:drp:{d}'] + CYCLE_ROWS
        files = run_files(str(tmp_path / f'wd-{d}'), rows, STAND_INS)
        runs[d] = (record(rows, files, tmp_path / 'evidence'), files)
    return status, tmp_path / 'evidence', runs


def test_valid_cycle_records_are_accepted(tmp_path):
    status, evidence, runs = cycle_runs(tmp_path)
    code, out = run_check(status, evidence)
    for row in [f'det:drp:{d}' for d in runs] + CYCLE_ROWS:
        print(line_of(out, row))
        assert 'evidence ' in line_of(out, row) and 'NO VALID' not in line_of(out, row)
    assert 'FAIL: 0 error(s), 0 RUN/STAND-IN row(s) without valid evidence,' in out
    assert 'stand-in simxpm (its PVs); evidence ' in line_of(out, 'prog:pyxpm')


def rehash(rec):
    """What a forger who knows the format also does: hash the files the record now lists."""
    rec['content'] = {f: {'bytes': os.path.getsize(f), 'sha256': coverage.content_hash(f, os.path.getsize(f))}
                      for f in rec['files'] if os.path.isfile(f)}


def swap_xtc2(data):
    """A mutation: the record lists a file holding `data` in place of its xtc2 file."""
    def mutate(rec, runs, d):
        xtc = [f for f in rec['files'] if f.endswith('.xtc2')][0]
        p = os.path.join(d, 'forged-' + os.path.basename(xtc))
        with open(p, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data(xtc))
        rec['files'] = [p if f.endswith('.xtc2') else f for f in rec['files']]
    return mutate


def head_bytes(n):
    return lambda path: open(path, 'rb').read(n)


CONFIGURE_ONLY = struct.pack('<QIIHHI', 0, 2 << 24, 0, 0, 0, 12)     # 24 B, as the skeptic made it
# The cases a skeptic ran against the evidence check (work/iter4-skeptic/mutcov.py), each
# as it edited the record (no hash updated) and again with the record's hashes recomputed:
# name: (row, mutation, why as edited, why when rehashed)
SKEPTIC = {
    'dirty-true': ('det:drp:wave8', lambda r, R, d: r.update(dirty=True),
                   'recorded with tracked files modified', None),
    'dirty-absent': ('det:drp:wave8he', lambda r, R, d: r.pop('dirty'),
                     'does not say the tree was clean', None),
    'runid-null': ('det:drp:epix100', lambda r, R, d: r.update(run_id=None), 'names no run (run_id)', None),
    'runid-blank': ('det:drp:wave8', lambda r, R, d: r.update(run_id='  '), 'names no run (run_id)', None),
    'other-sha': ('det:drp:epix100', lambda r, R, d: r.update(sha='f' * 40 if HEAD != 'f' * 40 else '0' * 40),
                  'not at HEAD', None),
    'xtc2-empty': ('det:drp:wave8', swap_xtc2(b''), 'files empty, e.g.', None),
    'xtc2-random': ('det:drp:wave8he', swap_xtc2(bytes(range(6, 256)) * 16), 'files unhashed, e.g.',
                    'files not xtc2, e.g.'),
    'xtc2-truncated': ('det:drp:wave8', swap_xtc2(head_bytes(20000)), 'files unhashed, e.g.',
                       'files not xtc2, e.g.'),
    'log-missing': ('det:drp:wave8he', lambda r, R, d: r['files'].__setitem__(1, r['files'][1] + '.gone'),
                    'files missing, e.g.', None),
    'probe-xtc2-tiny-configure': ('det:drp:epix100', swap_xtc2(CONFIGURE_ONLY), 'files unhashed, e.g.',
                                  'no listed xtc2 file has a detector of type epix100 in its Configure '
                                  '(they have: no detector)'),
    'probe-xtc2-of-other-det': ('det:drp:wave8he', lambda r, R, d: r.update(files=[
        [f for f in R['wave8'][1] if f.endswith('.xtc2')][0] if f.endswith('.xtc2') else f for f in r['files']]),
        'files unhashed, e.g.',
        'no listed xtc2 file has a detector of type wave8he in its Configure (they have: wave8)'),
    'probe-no-xtc2-listed': ('det:drp:wave8', lambda r, R, d: r.update(
        files=[f for f in r['files'] if not f.endswith('.xtc2')]), 'lists no xtc2 file', None),
}


@pytest.mark.parametrize('rehashed', [False, True], ids=['as-edited', 'rehashed'])
@pytest.mark.parametrize('case', sorted(SKEPTIC))
def test_skeptic_forgeries_are_rejected_naming_why(tmp_path, case, rehashed):
    """Each forged record drops its row, and the row's line says why; the other rows stay."""
    row, mutate, why, why_rehashed = SKEPTIC[case]
    status, evidence, runs = cycle_runs(tmp_path)
    path = runs[row.split(':')[2]][0]
    rec = json.load(open(path))
    mutate(rec, runs, str(tmp_path))
    if rehashed:
        rehash(rec)
    json.dump(rec, open(path, 'w'))
    code, out = run_check(status, evidence)
    line = line_of(out, row)
    print(line)
    assert code == 1 and 'NO VALID EVIDENCE' in line
    assert (why_rehashed if rehashed and why_rehashed else why) in line
    assert 'files not, e.g.' not in line
    assert f'  {row}: RUN row without valid evidence' in out
    for other in [f'det:drp:{d}' for d in runs if f'det:drp:{d}' != row] + CYCLE_ROWS:
        assert 'NO VALID' not in line_of(out, other), line_of(out, other)


def one_cycle_check(tmp_path, det='wave8he', mutate=None, rows=None, run_id=RUN_ID):
    """(exit code, output) for one cycle run's record: mutate(files) may change its files
    before the record is written (so it hashes them as they are)."""
    status, evidence, runs = cycle_runs(tmp_path, [det])
    path, files = runs[det]
    os.remove(path)
    if mutate:
        files = mutate(files) or files
    record(rows or [f'det:drp:{det}'] + CYCLE_ROWS, files, evidence, run_id=run_id)
    code, out = run_check(status, evidence)
    print('\n'.join(l for l in out.splitlines() if 'NO VALID' in l))
    return code, out


@pytest.mark.parametrize('events,with_data,why', [
    (3, None, '3 of its 3 L1Accepts hold wave8he data, fewer than 1000'),
    (999, None, '999 of its 999 L1Accepts hold wave8he data, fewer than 1000'),
    (1000, [], '0 of its 1000 L1Accepts hold wave8he data, fewer than 1000'),
])
def test_a_det_row_needs_1000_l1accepts_with_its_data(tmp_path, events, with_data, why):
    def mutate(files):
        write_run(files[0], [('wave8he', 'wave8he')], events=events, with_data=with_data)
    code, out = one_cycle_check(tmp_path, mutate=mutate)
    assert code == 1 and why in line_of(out, 'det:drp:wave8he')
    assert 'NO VALID' not in line_of(out, 'prog:teb')      # the run is still the record's run


def test_a_det_row_needs_its_type_in_the_configure(tmp_path):
    """The xtc2 file of another type (wave8 for wave8he), hashed by the record."""
    def mutate(files):
        write_run(files[0], [('wave8', 'wave8')])
    code, out = one_cycle_check(tmp_path, mutate=mutate)
    assert code == 1
    assert ('no listed xtc2 file has a detector of type wave8he in its Configure (they have: wave8)'
            in line_of(out, 'det:drp:wave8he'))


def test_the_record_run_id_must_be_the_files_run(tmp_path):
    def mutate(files):
        write_run(files[0], [('wave8he', 'wave8he')], run_id='tstx00001/r0002')
    code, out = one_cycle_check(tmp_path, mutate=mutate)
    assert code == 1
    assert 'its BeginRun is run tstx00001/r0002, the record says tstx00001/r0001' in line_of(out, 'det:drp:wave8he')
    assert ('lists no xtc2 file of run tstx00001/r0001 (by its BeginRun runinfo) to tie the log of teb to'
            in line_of(out, 'prog:teb'))


def test_a_det_row_needs_a_log_of_its_drp_and_type(tmp_path):
    def mutate(files):                                   # the drp log asks for another type
        write_log(files[1], 'drp -P tst -D wave8 -u wave8_0', f"Opening file '{files[0]}'")
    code, out = one_cycle_check(tmp_path, mutate=mutate)
    assert code == 1
    assert 'no listed log runs drp -D wave8he and names the run of' in line_of(out, 'det:drp:wave8he')


def test_a_drp_gpu_row_is_not_proven_by_a_drp_run(tmp_path):
    gpu = [r for r in all_rows() if r.startswith('det:drp_gpu:')][0]
    typ = gpu.split(':')[2]
    status = write_status(tmp_path / 'status.json', {gpu: {'status': 'RUN'}})
    files = run_files(str(tmp_path / 'run'), [f'det:drp:{typ}'])
    record([gpu], files, tmp_path / 'evidence')
    code, out = run_check(status, tmp_path / 'evidence')
    print(line_of(out, gpu))
    assert code == 1 and f'no listed log runs drp_gpu -D {typ} and names the run of' in line_of(out, gpu)


def test_a_program_row_needs_its_log_naming_the_run(tmp_path):
    def no_teb(files):
        return [f for f in files if not f.endswith('teb.log')]
    code, out = one_cycle_check(tmp_path / 'a', mutate=no_teb)
    assert code == 1 and 'lists no log of teb (a log whose "# CMDLINE:" runs teb)' in line_of(out, 'prog:teb')

    def other_run(files):                               # a teb log of another run
        write_log([f for f in files if f.endswith('teb.log')][0], 'teb -p 5',
                  'EbAppBase  saw        BeginRun @ 1163000000.000000001 (0473)')
    code, out = one_cycle_check(tmp_path / 'b', mutate=other_run)
    assert code == 1
    assert (f'its log of teb names neither the run\'s xtc2 file {tmp_path / "b" / "wd-wave8he"}'
            in line_of(out, 'prog:teb'))
    assert f'nor its BeginRun time {BEGINRUN_TIME}' in line_of(out, 'prog:teb')
    assert 'NO VALID' not in line_of(out, 'prog:control')


def test_a_log_may_name_the_xtc2_file_through_a_symlinked_dir(tmp_path):
    """up -w /sdf/data/... and cycle -w /sdf/scratch/... (one a symlink of the other): the DRP
    log names the file under one spelling, the record lists the other."""
    os.makedirs(tmp_path / 'real')
    os.symlink(tmp_path / 'real', tmp_path / 'link')
    xtc = write_run(tmp_path / 'link' / 'tstx00001-r0001-s000-c000.xtc2', [('wave8he', 'wave8he')])
    log = write_log(tmp_path / 'drp.log', 'drp -D wave8he',
                    f"Opening file '{tmp_path / 'real' / 'tstx00001-r0001-s000-c000.xtc2'}'")
    assert coverage.names_file(open(log).read(), xtc)
    assert not coverage.names_file(open(log).read(), str(tmp_path / 'link' / 'tstx00001-r0002-s000-c000.xtc2'))
    code, line, _ = one_row_check(tmp_path, [xtc, log], row='det:drp:wave8he')
    assert 'evidence ' in line and 'NO VALID' not in line


def test_a_stand_in_row_needs_the_stand_in_log(tmp_path):
    """prog:pyxpm is STAND-IN simxpm: a log that runs pyxpm itself does not prove it."""
    def pyxpm(files):
        write_log([f for f in files if f.endswith('simxpm.log')][0], 'pyxpm -P DAQ:SIM',
                  f'BeginRun time {BEGINRUN_TIME}')
    code, out = one_cycle_check(tmp_path, mutate=pyxpm)
    assert code == 1 and 'lists no log of simxpm' in line_of(out, 'prog:pyxpm')


def test_files_must_hold_the_bytes_the_record_hashed(tmp_path):
    status, evidence, runs = cycle_runs(tmp_path, ['wave8he'])
    path, files = runs['wave8he']
    xtc, teb = files[0], [f for f in files if f.endswith('teb.log')][0]

    def line():
        return line_of(run_check(status, evidence)[1], 'det:drp:wave8he')
    with open(teb, 'a') as f:                           # a log may grow after its record
        f.write('later output\n')
    assert 'NO VALID' not in line()
    data = bytearray(open(xtc, 'rb').read())
    data[-28] ^= 0xff                                   # same size, one byte of the last event's data
    open(xtc, 'wb').write(data)
    assert f'files changed, e.g. {xtc}: its first {len(data)} B are not the bytes the record hashed' in line()
    open(xtc, 'ab').write(b'\0' * 24)                   # an xtc2 file may not grow
    assert f'{xtc}: {len(data) + 24} B now, the record hashed {len(data)} B' in line()


def test_what_a_log_gains_after_its_record_does_not_count(tmp_path):
    """Run tokens appended to a log after the record was written do not tie it to the run."""
    def no_tokens(files):
        write_log([f for f in files if f.endswith('teb.log')][0], 'teb -p 5', 'nothing yet')
    status, evidence, runs = cycle_runs(tmp_path, ['wave8he'])
    path, files = runs['wave8he']
    os.remove(path)
    no_tokens(files)
    record(['det:drp:wave8he'] + CYCLE_ROWS, files, evidence)
    with open([f for f in files if f.endswith('teb.log')][0], 'a') as f:
        f.write(f'EbAppBase  saw        BeginRun @ {BEGINRUN_TIME} (047325138ca92b)\n')
    code, out = run_check(status, evidence)
    assert code == 1 and 'its log of teb names neither' in line_of(out, 'prog:teb')


def test_a_record_without_content_hashes_is_rejected(tmp_path):
    """Records written before content binding hold no hashes; they prove nothing."""
    status, evidence, runs = cycle_runs(tmp_path, ['wave8he'])
    path = runs['wave8he'][0]
    rec = json.load(open(path))
    rec.pop('content')
    json.dump(rec, open(path, 'w'))
    code, out = run_check(status, evidence)
    assert code == 1
    assert 'holds no content hashes of its files (content)' in line_of(out, 'det:drp:wave8he')


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


# --- witnesses: AMI (R1), GUIs and monitors (R2), PV-server stand-ins (R3) ----------------

AMI_ROWS = [f'prog:{p}' for p in coverage.AMI_PROGRAMS]


def ami_run(tmp_path, mutate=None):
    """(exit code, output) of one record for the AMI rows: the run's xtc2 file, each AMI program's
    procmgr log (with procServ's pid line) and the ami_check witness; mutate(witness, files) may
    change the witness (or return other files) before the record hashes them."""
    files = run_files(str(tmp_path / 'wd'), ['det:drp:fakecam'] + AMI_ROWS)
    wpath = [f for f in files if f.endswith('ami_check.json')][0]
    if mutate:
        w = json.load(open(wpath))
        files = mutate(w, files) or files
        write_witness(wpath, w)
    status = write_status(tmp_path / 'status.json', {r: {'status': 'RUN'} for r in AMI_ROWS})
    record(AMI_ROWS, files, tmp_path / 'evidence')
    return run_check(status, tmp_path / 'evidence')


def test_ami_rows_are_run_with_the_ami_check_of_the_run(tmp_path):
    code, out = ami_run(tmp_path)
    for r in AMI_ROWS:
        print(line_of(out, r))
        assert 'evidence ' in line_of(out, r) and 'NO VALID' not in line_of(out, r)


def drop_pid_line(w, files):
    log = [f for f in files if f.endswith('/ami-client.log')][0]
    write_log(log, f'{os.path.dirname(log)}/bin/ami-client -p 31150', 'no pid here')


# name: (mutation of the witness, what the ami-client row's line says)
AMI_FORGERIES = {
    'no-witness': (lambda w, files: [f for f in files if not f.endswith('ami_check.json')],
                   'lists no ami_check witness'),
    'other-run': (lambda w, f: w.update(run_id='tstx00001/r0002'),
                  'names run tstx00001/r0002, the record says tstx00001/r0001'),
    'unlisted-xtc2': (lambda w, f: w.update(xtc2=['/elsewhere/tstx00001-r0001-s000-c000.xtc2']),
                      'names no listed xtc2 file of run tstx00001/r0001'),
    'failed': (lambda w, f: w.update({'pass': False, 'problems': ['AMI row 0x1: seq 3, psana2 reads seq 4']}),
               'says the check failed'),
    'no-matches': (lambda w, f: w.update(matches=[]), 'lists no per-event match of AMI with psana2'),
    'match-not-in-run': (lambda w, f: w['matches'].append([l1_stamp(5000), 5000, 7]),
                         'is no L1Accept of the run\'s files'),
    'client-did-not-serve': (lambda w, f: w.update(served_by=[s for s in w['served_by']
                                                              if '/ami-client ' not in s['cmdline']]),
                             'its served_by lists no ami-client process'),
    'other-pid': (lambda w, f: [s.update(pid=s['pid'] + 100) for s in w['served_by']
                                if '/ami-client ' in s['cmdline']] and None,
                  'its log of ami-client gives pid 4000, not one of the ami-client processes that served '
                  'the check (4100)'),
    'log-without-pid': (drop_pid_line, 'its log of ami-client gives no pid'),
}


@pytest.mark.parametrize('case', sorted(AMI_FORGERIES))
def test_ami_forgeries_are_rejected_naming_why(tmp_path, case):
    mutate, why = AMI_FORGERIES[case]
    code, out = ami_run(tmp_path, mutate)
    line = line_of(out, 'prog:ami-client')
    print(line)
    assert code == 1 and 'NO VALID EVIDENCE' in line and why in line


def test_an_ami_gui_is_served_by_its_window_process(tmp_path):
    """ami-client's window (a forked 'ami editor') holds AMI's ports: its ancestor is the client whose
    log gives the pid ('# PID:', as ami_shot writes it); another pid there does not count."""
    def window(pid):
        def mutate(w, files):
            log = [f for f in files if f.endswith('/ami-client.log')][0]
            write_log(log, f'{os.path.dirname(log)}/bin/ami-client -p 31150 -g ami_shot', '# PID: 4000')
            client = [s for s in w['served_by'] if '/ami-client ' in s['cmdline']][0]
            w['served_by'] = [s for s in w['served_by'] if s is not client] + [
                {'pid': 5000, 'cmdline': 'ami editor', 'ancestors': [dict(client, pid=pid)]}]
        return mutate
    code, out = ami_run(tmp_path / 'a', window(4000))
    assert 'evidence ' in line_of(out, 'prog:ami-client') and 'NO VALID' not in line_of(out, 'prog:ami-client')
    code, out = ami_run(tmp_path / 'b', window(4001))
    assert code == 1 and ('its log of ami-client gives pid 4000, not one of the ami-client processes that '
                          'served the check (4001)') in line_of(out, 'prog:ami-client')


def test_log_pid_reads_procservs_line_as_it_writes_it():
    """procServ ends its lines with \\r\\n; the last pid line counts (a restart writes another)."""
    text = ('# CMDLINE: /w/bin/ami-manager -p 31150\n@@@ Restarting child "x:ami-manager.log"\r\n'
            '@@@ The PID of new child "x:ami-manager.log" is: 2681935\r\n@@@ @@@ @@@ @@@ @@@\r\n')
    assert coverage.log_pid(text) == 2681935
    assert coverage.log_pid(text + '@@@ The PID of new child "x:ami-manager.log" is: 2681999\r\n') == 2681999
    assert coverage.log_pid('# CMDLINE: ami-client -p 1\n# PID: 77\n') == 77
    assert coverage.log_pid('# CMDLINE: ami-client -p 1\nchild pid 77\n') is None


def test_an_ami_row_is_not_proven_by_a_log_naming_the_run(tmp_path):
    """An AMI program's log that names the BeginRun time is not its check (R1)."""
    def naming(w, files):
        log = [f for f in files if f.endswith('/ami-manager.log')][0]
        write_log(log, f'{os.path.dirname(log)}/bin/ami-manager -p 31150',
                  f'BeginRun @ {BEGINRUN_TIME}', '@@@ The PID of new child "x" is: 4002')
        return [f for f in files if not f.endswith('ami_check.json')]
    code, out = ami_run(tmp_path, naming)
    assert code == 1 and 'lists no ami_check witness' in line_of(out, 'prog:ami-manager')


def control_gui_run(tmp_path, path, data_dir='the run\'s'):
    """(exit code, line) of a record for prog:control_gui: the run's xtc2 file under <wd>/data and
    control_gui's log holding control's fileReport with `path`."""
    d = tmp_path / 'wd'
    xtc = write_run(d / 'data' / 'tst' / 'tstx00001' / 'xtc' / 'tstx00001-r0001-s000-c000.xtc2',
                    [('fakecam', 'fakecam')])
    log = write_log(d / 'control_gui.log', 'control_gui -H localhost -l DEBUG -e tstx00001 -p 5',
                    '<D> CGWMain.on_zmq_poll Flag zmq.POLLIN in 1 msg: [b\'{"header": {"key": "fileReport"}, '
                    f'"body": {{"path": "{path}"}}}}\']')
    status = write_status(tmp_path / 'status.json', {'prog:control_gui': {'status': 'RUN'}})
    record(['prog:control_gui'], [xtc, log], tmp_path / 'evidence',
           data_dir=str(d / 'data') if data_dir == 'the run\'s' else data_dir)
    code, out = run_check(status, tmp_path / 'evidence')
    print(line_of(out, 'prog:control_gui'))
    return code, line_of(out, 'prog:control_gui')


def test_a_log_may_name_the_xtc2_file_relative_to_the_data_dir(tmp_path):
    code, line = control_gui_run(tmp_path, '/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2')
    assert 'evidence ' in line and 'NO VALID' not in line


@pytest.mark.parametrize('path,data_dir', [
    ('/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2', None),               # record gives no data dir
    ('/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2', '/elsewhere/data'),  # another data dir
    ('/tst/tstx00001/xtc/tstx00001-r0002-s000-c000.xtc2', 'the run\'s'),       # another run's file
    ('/tst/tstx00002/xtc/tstx00001-r0001-s000-c000.xtc2', 'the run\'s'),       # resolves to no such file
], ids=['no-data-dir', 'other-data-dir', 'other-run', 'other-dir'])
def test_a_relative_path_counts_only_when_it_resolves_to_the_hashed_file(tmp_path, path, data_dir):
    code, line = control_gui_run(tmp_path, path, data_dir)
    assert code == 1 and 'NO VALID EVIDENCE' in line
    assert 'its log of control_gui names neither the run\'s xtc2 file' in line
    assert 'and it lists no gui_witness witness' in line


PARTITION = 'DAQ:SIM:XPM:0:PART:5'


def gui_witness(xtc2, progs, run_id=RUN_ID, section='programs', **entry):
    """A gui_witness as daq_sim cycle writes it: for each program (a GUI it ran offscreen, or a
    stand-in whose PVs it read) the span of its reads and the values of the partition's PVs."""
    e = {'pass': True, 'problems': [], 'start': L1_FIRST + 1, 'end': L1_FIRST + 5,
         'reads': [{'name': PARTITION + ':NumL0Acc', 'values': ['100', '250', '400']}]}
    e.update(entry)
    return {'witness': 'gui_witness', 'run_id': run_id, 'xtc2': [xtc2], 'partition': PARTITION,
            section: {p: dict(e) for p in progs}}


def witness_run(tmp_path, row='prog:groupca', cmd='groupca DAQ:SIM 0 5', stand_in=None, mutate=None,
                listed=True):
    """(exit code, line) of a record for one program row whose log never names the run: the run's
    xtc2 file, the program's (or stand-in's) log and a gui_witness for it."""
    d = tmp_path / 'wd'
    xtc = write_run(d / 'tstx00001-r0001-s000-c000.xtc2', [('fakecam', 'fakecam')])
    log = write_log(d / 'prog.log', cmd, 'Adding DAQ:SIM:XPM:0 to deadtime tree')
    prog = stand_in or row.split(':', 1)[1]
    w = gui_witness(xtc, [prog], section='servers' if stand_in else 'programs')
    if mutate:
        mutate(w, w['servers' if stand_in else 'programs'][prog])
    files = [xtc, log] + ([write_witness(d / 'gui_witness.json', w)] if listed else [])
    entry = {'status': 'STAND-IN', 'stand_in': stand_in, 'interface': 'its PVs'} if stand_in else {'status': 'RUN'}
    status = write_status(tmp_path / 'status.json', {row: entry})
    record([row], files, tmp_path / 'evidence')
    code, out = run_check(status, tmp_path / 'evidence')
    print(line_of(out, row))
    return code, line_of(out, row)


def test_a_gui_row_is_run_with_its_log_and_a_witness_of_the_run(tmp_path):
    code, line = witness_run(tmp_path)
    assert 'evidence ' in line and 'NO VALID' not in line


# name: (witness_run arguments, what the row's line says)
GUI_FORGERIES = {
    'not-listed': (dict(listed=False), 'and it lists no gui_witness witness'),
    'no-gui-log': (dict(cmd='pvant --bases DAQ:SIM:XPM:0:PART:5'), 'lists no log of groupca'),
    'other-run': (dict(mutate=lambda w, e: w.update(run_id='tstx00001/r0002')),
                  'names run tstx00001/r0002, the record says tstx00001/r0001'),
    'no-entry': (dict(mutate=lambda w, e: w.update(programs={'pvant': e})), 'has no programs entry for groupca'),
    'failed': (dict(mutate=lambda w, e: e.update({'pass': False, 'problems': ['walk exit 3']})),
               'says groupca failed'),
    'before-the-run': (dict(mutate=lambda w, e: e.update(start=L1_FIRST - 2)),
                       'not within the run\'s L1Accepts'),
    'after-the-run': (dict(mutate=lambda w, e: e.update(end=L1_LAST + 0.5)), 'not within the run\'s L1Accepts'),
    'not-live': (dict(mutate=lambda w, e: e.update(reads=[{'name': PARTITION + ':NumL0Acc', 'values': ['7', '7']}])),
                 'shows groupca read no live value under DAQ:SIM:XPM:0:PART:5'),
    'placeholder-then-value': (dict(mutate=lambda w, e: e.update(reads=[{'name': PARTITION + ':NumL0Acc',
                                                                         'values': ['-', '', '400']}])),
                               'shows groupca read no live value under DAQ:SIM:XPM:0:PART:5'),
    'other-partition': (dict(mutate=lambda w, e: e.update(reads=[{'name': 'DAQ:SIM:XPM:0:PART:3:NumL0Acc',
                                                                  'values': ['1', '2']}])),
                        'shows groupca read no live value under DAQ:SIM:XPM:0:PART:5'),
    'stand-in-section': (dict(mutate=lambda w, e: w.update(servers=w.pop('programs'))),
                         'has no programs entry for groupca'),
}


@pytest.mark.parametrize('case', sorted(GUI_FORGERIES))
def test_gui_witness_forgeries_are_rejected_naming_why(tmp_path, case):
    kw, why = GUI_FORGERIES[case]
    code, line = witness_run(tmp_path, **kw)
    assert code == 1 and 'NO VALID EVIDENCE' in line and why in line


def procstat_run(tmp_path, rows_shown):
    """(exit code, line) of a record for prog:procstat: the run's xtc2 file, a teb log (id teb0) and
    a drp log (id fakecam_0) that name the run, procstat's own log, and a gui_witness whose procstat
    entry ('kind': 'procmgr') is the table it showed: [(id, status)]."""
    d = tmp_path / 'wd'
    xtc = write_run(d / 'tstx00001-r0001-s000-c000.xtc2', [('fakecam', 'fakecam')])
    logs = []
    for pid, cmd, line in (('teb0', 'teb -P tst', f'BeginRun @ {BEGINRUN_TIME}'),
                           ('fakecam_0', 'drp -P tst -D fakecam', f"Opening file '{xtc}'"),
                           ('procstat', 'procstat -p 5 -i 1 /w/daq_sim.cnf', 'Refreshing')):
        p = d / f'{pid}.log'
        p.write_text(f'# ID:      {pid}\n# PLATFORM:5\n# CMDLINE: {cmd}\n{line}\n')
        logs.append(str(p))
    w = gui_witness(xtc, ['procstat'], kind='procmgr',
                    reads=[{'name': f'procmgr:{i}', 'values': [st]} for i, st in rows_shown])
    status = write_status(tmp_path / 'status.json', {'prog:procstat': {'status': 'RUN'}})
    record(['prog:procstat'], [xtc] + logs + [write_witness(d / 'gui_witness.json', w)], tmp_path / 'evidence')
    code, out = run_check(status, tmp_path / 'evidence')
    print(line_of(out, 'prog:procstat'))
    return code, line_of(out, 'prog:procstat')


def test_procstat_is_run_when_its_table_showed_the_runs_processes_running(tmp_path):
    code, line = procstat_run(tmp_path / 'a', [('control', 'RUNNING'), ('teb0', 'RUNNING'), ('fakecam_0', 'RUNNING'),
                                               ('procstat', 'RUNNING')])
    assert 'evidence ' in line and 'NO VALID' not in line
    code, line = procstat_run(tmp_path / 'b', [('teb0', 'RUNNING'), ('fakecam_0', 'SHUTDOWN')])
    assert code == 1 and 'shows procstat did not list fakecam_0 RUNNING' in line
    code, line = procstat_run(tmp_path / 'c', [('teb0', 'RUNNING')])
    assert code == 1 and 'shows procstat did not list fakecam_0 RUNNING' in line


def server_entry(w, e, missing=()):
    """Make a 'programs'-shaped entry the 'servers' entry of simxpm standing in for pykcuxpm: its
    own prefix and the interface of pykcuxpm."""
    e.update(prefix='DAQ:SIM:XPM:0', interfaces={'pykcuxpm': {'defined': 3, 'served': 3 - len(missing),
                                                              'missing': list(missing)}})


def test_a_pv_server_stand_in_is_proven_by_a_witness_of_its_pvs(tmp_path):
    """R3: a STAND-IN row whose stand-in's log never names the run needs a 'servers' entry: a
    client of the cycle read the stand-in's PVs while the run ran, and the entry shows the row
    program's PV names all served; a 'programs' entry is not one."""
    kw = dict(row='prog:pykcuxpm', cmd='python -m psdaq.sim.simxpm -P DAQ:SIM', stand_in='simxpm')
    code, line = witness_run(tmp_path / 'a', mutate=server_entry, **kw)
    assert 'stand-in simxpm (its PVs); evidence ' in line and 'NO VALID' not in line
    code, line = witness_run(tmp_path / 'b', mutate=lambda w, e: (server_entry(w, e), w.update(programs=w.pop('servers'))),
                             **kw)
    assert code == 1 and 'has no servers entry for simxpm' in line
    code, line = witness_run(tmp_path / 'c', mutate=lambda w, e: (server_entry(w, e), e.update(end=L1_LAST + 1)), **kw)
    assert code == 1 and 'not within the run\'s L1Accepts' in line
    code, line = witness_run(tmp_path / 'd', **kw)                        # no interface
    assert code == 1 and 'its simxpm entry shows no interface of pykcuxpm' in line
    code, line = witness_run(tmp_path / 'e', mutate=lambda w, e: server_entry(w, e, ['DAQ:SIM:XPM:0:XTPG:CuDelay']), **kw)
    assert code == 1 and 'simxpm does not serve 1 of the 3 PVs pykcuxpm defines, e.g. DAQ:SIM:XPM:0:XTPG:CuDelay' in line
    code, line = witness_run(tmp_path / 'f', mutate=lambda w, e: (server_entry(w, e), e.update(prefix='DAQ:SIM:HSD')),
                             **kw)                                        # its reads are not under its prefix
    assert code == 1 and 'shows simxpm read no live value under DAQ:SIM:HSD' in line


# --- the commands --------------------------------------------------------------------------

@pytest.mark.parametrize('argv', [['-m', 'psdaq.sim.coverage'], ['-m', 'psdaq.sim.daq_sim', 'coverage'],
                                  ['-m', 'psdaq.sim.daq_sim', 'matrix', '--only', 'coverage']])
def test_commands_return_the_verdict(tmp_path, argv):
    rows, status, evidence, files = full_coverage(tmp_path)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(REPO, 'psdaq')] + sys.path))
    env.pop('SIM_ENV_SOURCED', None)
    cmd = [sys.executable] + argv + ['--repo', REPO, '--status', str(status), '--evidence', str(evidence)]
    if 'matrix' in argv:
        cmd += ['-w', str(tmp_path / 'matrix')]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert r.stdout.rstrip().endswith('MATRIX PASS (1 assertions)' if 'matrix' in argv else 'PASS')
    os.remove(files[0])
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 1 and 'FAIL' in r.stdout
