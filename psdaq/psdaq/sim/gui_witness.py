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
run's L1Accepts, so the values were read while the run ran.
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
PORT_LINE = re.compile(r'Providing run-time monitoring data on port (\d+)')


def argv(name, params):
    return [a.format(**params) for a in (WITNESS.get(name) or MONITORS[name])['argv']]


def spec(name, params):
    """The qt_walk --gui spec of a passive walk of GUI `name`."""
    return {'file': WITNESS[name]['file'], 'web': None, 'backend': 'sim-daq',
            'walk': {'argv': WITNESS[name]['argv'], 'pump': 3, 'timeout': 60,
                     'drive': ['pump:1'] * PUMPS, 'record_calls': WITNESS[name].get('record_calls', [])}}


def start(workdir, name, outdir, env=None):
    """Start the passive walk of GUI `name` against the simulated DAQ in workdir; returns
    (Popen, walk path, log path, Unix start time)."""
    os.makedirs(outdir, exist_ok=True)
    sp, walk = os.path.join(outdir, f'{name}.spec.json'), os.path.join(outdir, f'{name}.walk.json')
    log = os.path.join(outdir, f'{name}.walk.log')
    with open(sp, 'w') as f:
        json.dump(spec(name, {}), f, indent=1)
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
    else:
        e['reads'] = [r for r in reads(walk) if r['name'].startswith(prefix)]
        live = [r['name'] for r in e['reads'] if len(numbers(r['values'])) >= 2]
        if not live:
            e['problems'].append(f'no PV under {prefix} showed 2 or more distinct numbers')
    e['live'] = live
    e['pass'] = not e['problems']
    return e


def witness(run_id, xtc2, prefix, programs):
    return {'witness': 'gui_witness', 'run_id': run_id, 'xtc2': list(xtc2), 'partition': prefix,
            'programs': programs}


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
