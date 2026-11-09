"""gui_witness: the PyQt GUIs of 'daq_sim up --gui' read the run's partition while it runs.

    python -m psdaq.sim.gui_witness walk --sim-daq WORKDIR --gui NAME --out WALK.json
    daq_sim cycle runs it, for every GUI of WITNESS that 'up --gui' started, once the run is Running

A GUI such as groupca never logs a run: it shows PVs.  So while the run is Running, cycle runs each
such GUI's own main() offscreen once more, through the parity check's walk
(psdaq.webgui.parity.qt_walk --gui), with the argv its procmgr entry gives it and a passive drive
(event pumps only: nothing is clicked, nothing written), and keeps the text every PV-bound widget
shows after each pump.  witness() turns the walks into the witness 'daq_sim coverage' reads
(psdaq.sim.coverage; cycle writes it to logs/gui_witness.json and lists it in the run's record):

  {"witness": "gui_witness", "run_id": "<expt>/r<run>", "xtc2": [the run's files],
   "partition": "<pvbase>:XPM:<xpm>:PART:<platform>",
   "programs": {name: {"pass", "problems", "argv", "walk", "exit",
                       "start", "end" (EPICS-epoch seconds, the walk's process),
                       "reads": [{"name": <PV>, "values": [<texts in order>]}]}}}

A program passes if its walk exited 0 and at least one widget bound to a PV under the partition
prefix showed 2 or more distinct numbers.  Coverage also checks that [start, end] lies within the
run's L1Accepts, so the values were read while the run ran, and that the values are ones the PV's
server logged it served then (psdaq.sim.served_log).

procstat's entry ("kind": "procmgr") also holds "before" and "after": procstat's table read once
more by cycle in Configured before BeginRun and after EndRun (snapshot_entry: "walk", "exit",
"start", "end", "reads", and "procmgr_pids", the pids 'procmgr status' gave right after the walk).
Coverage counts a GUI or monitor row only if procmgr's own instance of it is RUNNING in all three
tables, with the one child pid its procmgr logs name in "before" and "after", so the same process
ran from before the run to after it.

A GUI whose PVs come from a device stand-in (R4: hsdpva on simhsd, tprca on simtpr, dtica on simdti,
started by 'daq_sim up --pvservers') walks with a PVA client that searches only that stand-in's ports;
its entry adds "stand_in" and "prefix" (the stand-in's PVs), and its reads are one per widget
({"name": <PV>, "widget": "<class>#<n>", "values": [...]}) under that prefix; it passes if one widget
showed 2 or more distinct values after its first text (psdaq.sim.coverage.changed_texts).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

EPICS_EPOCH = 631152000                 # 1990-01-01 in Unix seconds
# The GUIs whose reads are witnessed: the parity check's file of each (psdaq/psdaq/<file>) and the
# argv daq_sim's procmgr entry gives it ({pvbase} {xpm} {platform} {part} from the work dir, as
# qt_walk's sim_params gives them).  The configs start groupca as 'groupca DAQ:<hutch> <xpm>
# <group>' (asc.cnf) and pvant on a list of bases and fields (lab3-wave8.cnf).  (xpmpva is not
# here: it reads <xpm>:Us:RxAlign at startup, a PV this simxpm does not serve, and exits.)
WITNESS = {
    'groupca': {'file': 'cas/groupca.py', 'argv': ['{pvbase}', '{xpm}', '{platform}']},
    # procstat (the configs: procstat <CONFIGDIR>/p<platform>.cnf.last) shows procmgr's table of the
    # partition's processes, ID and status, polled every -i s: its reads are the rows it showed,
    # 'procmgr:<id>' with the status, and coverage checks that every process whose log names the
    # run was among them RUNNING.  The calls its menus would make for real are recorded instead.
    'procstat': {'file': 'procmgr/procstat', 'argv': ['-p', '{platform}', '-i', '1', '{cnf}'], 'kind': 'procmgr',
                 'record_calls': ['psdaq.procmgr.ProcMgr:ProcMgr.spawnConsole', 'psdaq.procmgr.ProcMgr:ProcMgr.spawnLogfile',
                                  'psdaq.procmgr.ProcMgr:ProcMgr.stop', 'psdaq.procmgr.ProcMgr:ProcMgr.start']},
    # partca (lab3-cam.cnf: partca DAQ:LAB2:PART:<platform>) on the partition's PVs
    'partca':  {'file': 'cas/partca.py', 'argv': ['{part}']},
    'pvant':   {'file': 'cas/pvant.py',
                'argv': ['--bases', '{part}', '--fields', 'NumL0Acc', 'NumL0Inp', 'L0AccRate']},
    # R4: GUIs whose PVs come from a device stand-in of SERVERS ('server'), which daq_sim up --pvservers starts;
    # up --gui --pvservers starts them as the configs do: hsdpva <bases> (test-hsd.cnf: hsdpva <pvlist>), tprca
    # <prefix> (xcs.cnf: tprca DAQ:XCS:TPR), dtica <prefix> (lab3-cam.cnf: launch_py <bins>/dtica.py
    # DAQ:LAB2:DTI:<shelf>; no dtica console script, so python -m).  Their reads are kept per widget (a structure
    # PV such as <hsd>:MONTIMING shows each field in a widget of its own).  (pvatable and deadca are not here: their
    # value widgets hold no PV the walk can name; see SERVER_GUI_BLOCKERS.)
    'hsdpva':  {'file': 'cas/hsdpva.py', 'argv': ['{pvbase}:HSD:1_DA:A', '{pvbase}:HSD:1_DA:B'], 'server': 'simhsd'},
    'tprca':   {'file': 'cas/tprca.py', 'argv': ['{pvbase}:TPR'], 'server': 'simtpr'},
    'dtica':   {'file': 'cas/dtica.py', 'argv': ['{pvbase}:DTI'], 'server': 'simdti', 'module': 'psdaq.cas.dtica'},
}
# The GUIs on a device stand-in that are not witnessed yet, and why (RUNBOOK §3d, R4).
SERVER_GUI_BLOCKERS = {
    'pvatable': 'its value widgets (PvField, a QLabel) hold no PV: PvManager keeps the PV and calls them back, so '
                'the walk, which names a widget\'s PV by a pv attribute on it or its parents, binds none',
    'deadca': 'its value widgets (PvDblArrayW, a QLabel) hold no PV either: a PvDblArray object holds it and sets '
              'their text (0 PV-bound reads in a walk against simxpm)',
    'daqstat': 'it reads no PV: its rows are Slurm job states (daqmgr), answered by simslurm, not a PV stand-in',
    'xpmpva': 'it reads <xpm>:Us:RxAlign at start, which simxpm does not serve, and exits',
}
PUMPS = 4                               # snapshots after the first pump, one per second
# PV monitors that are not GUIs, witnessed the same way: epics_exporter (the configs' pvrtmon-*
# processes, e.g. neh-base.cnf: epics_exporter -H tst -I xpm-0 -M <prom dir> -P DAQ:NEH:XPM:0 ...
# DeadFrac) serves the partitions' PVs <prefix>:PART:<0..7>:<name> as Prometheus gauges labelled
# partition=<i>; cycle scrapes it once a second while the run is Running.
MONITORS = {
    'epics_exporter': {'id': 'pvrtmon_0',
                       'argv': ['-H', 'tst', '-I', 'xpm-{xpm}', '-M', '{prom}', '-P', '{pvbase}:XPM:{xpm}',
                                'NumL0Acc', 'NumL0Inp', 'RunTime']},
}
# PV-server stand-ins (R3) daq_sim up --pvservers starts, each on PVA ports of its own (so simxpm stays the
# only server on the node's search port): what the cycle reads of each while Running (a PV and a field that
# changes once a second) and the programs it stands in for, each with the PV names that program's own source
# defines (interface()).
SERVERS = {
    'simhsd': {'args': ['-P', '{pvbase}:HSD:1_DA:A', '{pvbase}:HSD:1_DA:B'], 'prefix': '{pvbase}:HSD:1_DA',
               'live': [('{pvbase}:HSD:1_DA:A:MONTIMING', 'timframecnt'), ('{pvbase}:HSD:1_DA:B:MONTIMING', 'trigcntsum')],
               'programs': ['hsdpvs']},
    'simtpr': {'args': ['-P', '{pvbase}:TPR'], 'prefix': '{pvbase}:TPR',
               'live': [('{pvbase}:TPR:EVTCNT', None)], 'programs': ['tprcas']},
    'simdti': {'args': ['-P', '{pvbase}:DTI'], 'prefix': '{pvbase}:DTI',
               'live': [('{pvbase}:DTI:3:TimFrRate', None)], 'programs': ['dticas']},
}


def pva_env(port):
    """The environment of a PVA client that searches only the stand-in whose search (broadcast) port is
    `port` on 127.0.0.1 (as pva_context, for a GUI process)."""
    return {'EPICS_PVA_ADDR_LIST': '127.0.0.1', 'EPICS_PVA_AUTO_ADDR_LIST': 'NO',
            'EPICS_PVA_BROADCAST_PORT': str(port)}
PORT_LINE = re.compile(r'Providing run-time monitoring data on port (\d+)')


def argv(name, params):
    return [a.format(**params) for a in (WITNESS.get(name) or MONITORS[name])['argv']]


def witnessed(gui=True, pvservers=False):
    """The GUIs of WITNESS that 'up' starts: those on the partition with --gui, those on a device stand-in
    (R4) only with --pvservers too."""
    return [n for n, w in WITNESS.items() if gui and (pvservers or not w.get('server'))]


def spec(name, params, pumps=PUMPS):
    """The qt_walk --gui spec of a passive walk of GUI `name`."""
    return {'file': WITNESS[name]['file'], 'web': None, 'backend': 'sim-daq',
            'walk': {'argv': WITNESS[name]['argv'], 'pump': 3, 'timeout': 60,
                     'drive': ['pump:1'] * pumps, 'record_calls': WITNESS[name].get('record_calls', [])}}


def start(workdir, name, outdir, env=None, label=None, pumps=PUMPS):
    """Start the passive walk of GUI `name` against the simulated DAQ in workdir; returns
    (Popen, walk path, log path, Unix start time).  label names its files (default: name)."""
    os.makedirs(outdir, exist_ok=True)
    tag = name if label is None else f'{name}-{label}'
    sp, walk = os.path.join(outdir, f'{tag}.spec.json'), os.path.join(outdir, f'{tag}.walk.json')
    log = os.path.join(outdir, f'{tag}.walk.log')
    with open(sp, 'w') as f:
        json.dump(spec(name, {}, pumps), f, indent=1)
    cmd = [sys.executable, '-m', 'psdaq.webgui.parity.qt_walk', '--gui', sp, '--sim-daq', workdir, '--out', walk]
    env = dict(env or os.environ, QT_QPA_PLATFORM='offscreen')
    t0 = time.time()
    with open(log, 'w') as out:
        p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                             cwd=outdir)
    return p, walk, log, t0


def table_reads(walk):
    """[{'name': 'procmgr:<id>', 'values': [status]}] of the rows procstat's table showed at the end
    of a qt_walk --gui result (its first two columns, ID and status)."""
    out = []
    for inst in walk.get('instances', []):
        for row in inst.get('cells') or []:
            if len(row) >= 2 and row[0]:
                out.append({'name': f'procmgr:{row[0]}', 'values': [str(row[1] or '').strip()]})
    return out


def snapshot_entry(walk_path, code, t0, t1, pids=None):
    """procstat's table read once (cycle: in Configured, before BeginRun or after EndRun): its walk, exit code,
    start and end (EPICS-epoch seconds, the walk's process), its rows, as table_reads gives them, and pids
    ({procmgr id: pid}, what 'procmgr status' gave right after the walk) as 'procmgr_pids'."""
    e = {'walk': walk_path, 'exit': code, 'start': round(t0 - EPICS_EPOCH, 3), 'end': round(t1 - EPICS_EPOCH, 3),
         'reads': [], 'problems': []}
    if pids is not None:
        e['procmgr_pids'] = dict(pids)
    try:
        with open(walk_path) as f:
            e['reads'] = table_reads(json.load(f))
    except (OSError, ValueError) as ex:
        e['problems'].append(f'no walk result: {ex}')
    if code != 0:
        e['problems'].append(f'walk exited {code}')
    return e


def reads(walk):
    """[{'name': PV, 'values': [texts]}] of every widget bound to a PV in a qt_walk --gui result."""
    out = {}
    for inst in walk.get('instances', []):
        pv = inst.get('pv')
        if not pv:
            continue
        values = [t for _, t in inst.get('texts') or [] if t is not None]
        if inst.get('text') is not None and (not values or values[-1] != inst['text']):
            values.append(inst['text'])
        out.setdefault(pv, [])
        for v in values:
            if not out[pv] or out[pv][-1] != v:
                out[pv].append(v)
    return [{'name': k, 'values': v} for k, v in sorted(out.items())]


def widget_reads(walk):
    """[{'name': PV, 'widget': '<class>#<n>', 'values': [texts]}]: one per widget bound to a PV in a qt_walk
    --gui result, its texts in order (repeats dropped), so 2 numbers in one read are one widget's change."""
    out = []
    for n, inst in enumerate(walk.get('instances', [])):
        if not inst.get('pv'):
            continue
        values = [t for _, t in inst.get('texts') or [] if t is not None]
        if inst.get('text') is not None and (not values or values[-1] != inst['text']):
            values.append(inst['text'])
        kept = []
        for v in values:
            if not kept or kept[-1] != v:
                kept.append(v)
        out.append({'name': inst['pv'], 'widget': f'{inst.get("cls") or "?"}#{n}', 'values': kept})
    return sorted(out, key=lambda r: (r['name'], r['widget']))


def exporter_port(log):
    """The Prometheus port an epics_exporter log says it serves on, or None."""
    try:
        with open(log, errors='replace') as f:
            ports = PORT_LINE.findall(f.read())
    except OSError:
        return None
    return int(ports[-1]) if ports else None


def scrape_reads(port, names, xpm_prefix, seconds, period=1.0, scrape=None):
    """Scrape an epics_exporter for `seconds`: (Unix start, Unix end, reads), reads as reads() gives
    them, one per (name, partition) gauge, named by the PV it exports (<xpm_prefix>:PART:<i>:<name>)."""
    if scrape is None:
        from psdaq.sim.daq_sim import scrape
    out, t0 = {}, time.time()
    end = t0 + seconds
    while True:
        for k, v in scrape(port, names).items():
            m = re.match(r'(\w+)\{.*partition="(\d+)"', k)
            if m:
                vals = out.setdefault(f'{xpm_prefix}:PART:{m.group(2)}:{m.group(1)}', [])
                text = f'{v:g}'
                if not vals or vals[-1] != text:
                    vals.append(text)
        if time.time() >= end:
            break
        time.sleep(period)
    return t0, time.time(), [{'name': k, 'values': v} for k, v in sorted(out.items())]


def monitor_entry(name, port, t0, t1, reads, prefix, params):
    """The witness entry of a monitor's scrapes (as entry() for a GUI's walk)."""
    e = {'argv': argv(name, params), 'port': port, 'exit': None,
         'start': round(t0 - EPICS_EPOCH, 3), 'end': round(t1 - EPICS_EPOCH, 3), 'problems': [],
         'reads': [r for r in reads if r['name'].startswith(prefix)]}
    if port is None:
        e['problems'].append('its log names no Prometheus port')
    live = [r['name'] for r in e['reads'] if len(numbers(r['values'])) >= 2]
    if not live:
        e['problems'].append(f'no PV under {prefix} showed 2 or more distinct numbers')
    e['live'] = live
    e['pass'] = not e['problems']
    return e


def hsdpvs_names(prefixes):
    """The PV names psdaq/psdaq/cas/hsdpvs.py serves for `hsdpvs -P <prefixes>`: its ChipServer adds
    them to the provider it is given, here one that only keeps the names."""
    from psdaq.cas import hsdpvs

    class Names:
        def __init__(self):
            self.names = []

        def add(self, name, pv):
            self.names.append(name)
    prov = Names()
    for p in prefixes:
        hsdpvs.ChipServer(prov, p, False)
    return sorted(prov.names)


def tprcas_names(prefix):
    """The PV names psdaq/psdaq/cas/tprcas.py serves for `tprcas -P <prefix>`: its main() builds its PV
    table and hands it to PVAServer.createPV, here a stand-in that keeps the table and serves nothing."""
    import contextlib
    import io
    import sys as _sys
    from psdaq.cas import tprcas
    got = []

    class Keep:
        def __init__(self, *a, **k):
            pass

        def createPV(self, pfx, pvdb):
            got.extend(pfx + k for k in pvdb)

        def forever(self):
            pass
    argv, orig = _sys.argv, tprcas.PVAServer
    try:
        _sys.argv, tprcas.PVAServer = ['tprcas', '-P', prefix], Keep
        with contextlib.redirect_stdout(io.StringIO()):     # it prints its table
            tprcas.main()
    finally:
        _sys.argv, tprcas.PVAServer = argv, orig
    return sorted(got)


def interface(program, args):
    """The PV names `program`'s own source defines for the stand-in's -P args."""
    prefixes = args[args.index('-P') + 1:] if '-P' in args else []
    if program == 'hsdpvs':
        return hsdpvs_names(prefixes)
    if program == 'tprcas':
        return tprcas_names(prefixes[0])
    if program == 'dticas':             # the table dticas.main builds (simdti serves exactly it)
        from psdaq.sim.simdti import dticas_table
        pfx, table = dticas_table(prefixes[0])
        return sorted(pfx + k for k in table)
    raise KeyError(program)


def pva_context(port):
    """A p4p client context that searches only the PVA server whose search (broadcast) port is `port`
    on 127.0.0.1."""
    from p4p.client.thread import Context
    return Context('pva', conf={'EPICS_PVA_ADDR_LIST': f'127.0.0.1:{port}', 'EPICS_PVA_AUTO_ADDR_LIST': 'NO',
                                'EPICS_PVA_BROADCAST_PORT': str(port)}, useenv=False)


def server_prepare(name, params, port):
    """(args, {program: the PV names its source defines}, a client context for the stand-in): what
    server_entry needs, made in the calling thread (the imports of the programs' modules and of p4p
    must not run in a reader thread while the main thread imports too: Python's import locks then
    deadlock, as seen at 07ba5ab75)."""
    args = [a.format(**params) for a in SERVERS[name]['args']]
    return args, {prog: interface(prog, args) for prog in SERVERS[name]['programs']}, pva_context(port)


def server_entry(name, params, port, seconds, period=1.0, prepared=None):
    """A 'servers' witness entry for stand-in `name`: its interface for each program it stands in for
    (every name the program defines, got once from the stand-in) and its live PVs read once a second
    for `seconds`, while the run runs.  prepared: server_prepare()'s result."""
    S = SERVERS[name]
    args, defined, ctx = prepared or server_prepare(name, params, port)
    e = {'args': args, 'port': port, 'prefix': S['prefix'].format(**params), 'interfaces': {}, 'reads': [],
         'problems': []}
    t0 = time.time()
    for prog in S['programs']:
        names = defined[prog]
        got = ctx.get(names, timeout=5.0, throw=False)
        missing = [n for n, v in zip(names, got) if isinstance(v, Exception)]
        e['interfaces'][prog] = {'defined': len(names), 'served': len(names) - len(missing), 'missing': missing}
        if missing:
            e['problems'].append(f'{name} does not serve {len(missing)} of {prog}\'s {len(names)} PVs, e.g. {missing[:3]}')
    reads = {}
    end = time.time() + seconds
    while True:
        for pv, field in S['live']:
            pv = pv.format(**params)
            try:
                v = ctx.get(pv, timeout=2.0)
                x = v[field] if field else v
                x = getattr(x, 'raw', x)
                x = x.value if hasattr(x, 'value') else x
                text = f'{float(x):g}'
            except Exception as ex:
                text = f'error {type(ex).__name__}'
            key = pv + ('.' + field if field else '')
            vals = reads.setdefault(key, [])
            if not vals or vals[-1] != text:
                vals.append(text)
        if time.time() >= end:
            break
        time.sleep(period)
    e['start'], e['end'] = round(t0 - EPICS_EPOCH, 3), round(time.time() - EPICS_EPOCH, 3)
    e['reads'] = [{'name': k, 'values': v} for k, v in sorted(reads.items())]
    e['live'] = [r['name'] for r in e['reads'] if len(numbers(r['values'])) >= 2]
    if not e['live']:
        e['problems'].append(f'no PV of {name} showed 2 or more distinct numbers')
    e['pass'] = not e['problems']
    return e


def numbers(values):
    from psdaq.sim.coverage import numbers as n
    return n(values)


def entry(name, walk_path, code, t0, t1, prefix, params):
    """The witness entry of one GUI's walk."""
    e = {'argv': argv(name, params), 'walk': walk_path, 'exit': code,
         'start': round(t0 - EPICS_EPOCH, 3), 'end': round(t1 - EPICS_EPOCH, 3), 'reads': [], 'problems': []}
    try:
        with open(walk_path) as f:
            walk = json.load(f)
    except (OSError, ValueError) as ex:
        walk = {}
        e['problems'].append(f'no walk result: {ex}')
    if code != 0:
        e['problems'].append(f'walk exited {code}' + (f': {walk.get("notes", [])[:1]}' if walk else ''))
    if walk and walk.get('argv') != e['argv']:
        e['problems'].append(f'walk ran argv {walk.get("argv")}, the procmgr entry gives {e["argv"]}')
    if WITNESS[name].get('kind') == 'procmgr':
        e['kind'] = 'procmgr'
        e['reads'] = table_reads(walk)
        live = [r['name'] for r in e['reads'] if r['values'][-1:] == ['RUNNING']]
        if not live:
            e['problems'].append('its table showed no process RUNNING')
    elif WITNESS[name].get('server'):   # R4: the PVs of a device stand-in, one read per widget
        server = WITNESS[name]['server']
        sprefix = SERVERS[server]['prefix'].format(**params)
        e.update(stand_in=server, prefix=sprefix)
        e['reads'] = [r for r in widget_reads(walk) if r['name'].startswith(sprefix)]
        from psdaq.sim.coverage import changed_texts
        live = sorted({r['name'] for r in e['reads'] if len(changed_texts(r['values'])) >= 2})
        if not live:
            e['problems'].append(f'no widget bound to a PV under {sprefix} ({server}) showed 2 or more distinct values '
                                 f'after its first text')
    else:
        e['reads'] = [r for r in reads(walk) if r['name'].startswith(prefix)]
        live = [r['name'] for r in e['reads'] if len(numbers(r['values'])) >= 2]
        if not live:
            e['problems'].append(f'no PV under {prefix} showed 2 or more distinct numbers')
    e['live'] = live
    e['pass'] = not e['problems']
    return e


def witness(run_id, xtc2, prefix, programs, servers=None):
    return {'witness': 'gui_witness', 'run_id': run_id, 'xtc2': list(xtc2), 'partition': prefix,
            'programs': programs, 'servers': servers or {}}


def main(argv_=None):
    parser = argparse.ArgumentParser(prog='python -m psdaq.sim.gui_witness',
                                     description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    parser.add_argument('action', choices=('walk',))
    parser.add_argument('--sim-daq', required=True, help='the daq_sim work dir of the running DAQ')
    parser.add_argument('--gui', required=True, choices=sorted(WITNESS))
    parser.add_argument('--out', required=True, help='dir for the walk, its spec and its log')
    args = parser.parse_args(argv_)
    p, walk, log, t0 = start(os.path.abspath(args.sim_daq), args.gui, args.out)
    code = p.wait(120)
    from psdaq.webgui.parity.qt_walk import sim_params
    params = sim_params(os.path.abspath(args.sim_daq))
    e = entry(args.gui, walk, code, t0, time.time(), params['part'], params)
    print(json.dumps(e, indent=1))
    return 0 if e['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
