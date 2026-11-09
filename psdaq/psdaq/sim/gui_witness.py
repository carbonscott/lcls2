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

A GUI whose PVs come from a device stand-in (R4: hsdpva and pvatable on simhsd, tprca on simtpr, dtica on simdti,
started by 'daq_sim up --pvservers'; xpmpva and deadca on simxpm) walks with a PVA client that searches only that
stand-in's ports; its entry adds "stand_in" and "prefix" (the stand-in's PVs), and its reads are one per widget
({"name": <PV>, "widget": "<class>#<n>", "values": [...]}) under that prefix; it passes if one widget
showed 2 or more distinct values after its first text (psdaq.sim.coverage.changed_texts).  deadca's entry adds
"stimulus": the link the cycle had assert full during the walks (simxpm SIM:LinkFull), its share and when.

daqstat (R5) reads no PV: its entry ("kind": "slurm") holds the walk's refreshes of its table and the cycle's own squeue
reads of simslurm meanwhile.  The tree's own PV servers (PROGRAM_SERVERS: bldcas, hpsdbuscas) get a 'servers' entry
keyed by the program (R3b), the stand-ins of SERVERS one keyed by the stand-in (R3).  The TPR programs ('daq_sim up
--tpr': tprtrig, tpr_trigger, each on a simulated TPR card) get a 'programs' entry ("kind": "tpr", R8) with their card's
channel and trigger registers, read once a second; lclsBldServer, on a card whose frames psdaq.sim.tprframes delivers,
one of "kind": "bld" that also holds the BLD packets a receiver on its group (loopback, off the production network)
got meanwhile.
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
# <group>' (asc.cnf) and pvant on a list of bases and fields (lab3-wave8.cnf).
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
    # PV such as <hsd>:MONTIMING shows each field in a widget of its own).
    'hsdpva':  {'file': 'cas/hsdpva.py', 'argv': ['{pvbase}:HSD:1_DA:A', '{pvbase}:HSD:1_DA:B'], 'server': 'simhsd'},
    'tprca':   {'file': 'cas/tprca.py', 'argv': ['{pvbase}:TPR'], 'server': 'simtpr'},
    'dtica':   {'file': 'cas/dtica.py', 'argv': ['{pvbase}:DTI'], 'server': 'simdti', 'module': 'psdaq.cas.dtica'},
    # pvatable as test-hsd.cnf starts it (pvatable --bases <pvlist> --fields <fields>), on simhsd: its PvField labels
    # hold no PV, a PvManager's PvBase does and calls them back; the walk names a widget by the object that holds
    # it with a PV (qt_walk find_pv: a holder's 'fields' or 'widgets'), so each label is bound to its PV
    'pvatable': {'file': 'cas/pvatable.py', 'server': 'simhsd',
                 'argv': ['--bases', '{pvbase}:HSD:1_DA:A', '{pvbase}:HSD:1_DA:B', '--fields', 'MONTIMING.trigcntsum',
                          'MONTIMING.readcntsum', 'MONTIMING.startcntsum', 'MONTIMING.headercntl0',
                          'MONTIMING.headerfifow', 'MONPGP.txcntsum', 'MONRAWBUF.freesz', 'MONRAWBUF.freeevt']},
    # xpmpva <xpm> (lab3-cam.cnf: xpmpva DAQ:LAB2:XPM:<shelf>) on simxpm, the XPM stand-in on the node's own PVA
    # ports ('prefix': no SERVERS entry): it reads <xpm>:Us:RxAlign and PAddr at start, which simxpm serves
    'xpmpva':  {'file': 'cas/xpmpva.py', 'argv': ['{pvbase}:XPM:{xpm}'], 'server': 'simxpm',
                'prefix': '{pvbase}:XPM:{xpm}'},
    # deadca <base> <partition> <shelf> (lab3-cam.cnf: launch_py <bins>/deadca.py DAQ:LAB2 <platform> <shelf>; no deadca
    # console script, so python -m) on simxpm: its labels show the partition's DeadFLnk, one per link (PvDblArray sets
    # them).  A healthy run has no deadtime, so while the walks run the cycle has the first DRP's link assert full for
    # LINK_FULL of every simxpm FULL_PERIOD (simxpm SIM:LinkFull, as a DRP whose readout stalls), then not; simxpm holds
    # the group's L0s back meanwhile and posts each second's share in DeadFLnk, as an XPM does (the entry's 'stimulus')
    'deadca':  {'file': 'cas/deadca.py', 'argv': ['{pvbase}', '{platform}', '{xpm}'], 'server': 'simxpm',
                'prefix': '{pvbase}:XPM:{xpm}', 'module': 'psdaq.cas.deadca', 'link_full': 'fakecam_0'},
    # R5: daqstat reads no PV but the Slurm job of each process of a daqmgr config (mfx.py: daqstat -i 5), here the
    # campaign's own DAQ: 'up --gui' has simslurm hold a job for each process of daq_sim.cnf (converted by daqmgr's
    # cnftopy) and answer daqstat's Slurm commands (PATH shims for the procmgr one; the walk's psdaq.slurm.utils
    # subprocess).  The walk records each refresh of its table with its time; the cycle reads squeue from simslurm
    # itself meanwhile, and coverage checks that 2 or more refreshes during the run showed what squeue said.
    'daqstat': {'file': 'slurm/daqstat.py', 'argv': ['-i', '1', '{workdir}/slurm/daqstat.py'], 'kind': 'slurm',
                'slurm_state': '{workdir}/slurm/state.json', 'env': {'HOME': '{workdir}/slurm/home'},
                'refresh_calls': ['psdaq.slurm.daqstat:WinProcStat.onProcMgrUpdated'],
                'record_calls': ['psdaq.slurm.main:Runner.spawnConsole', 'psdaq.slurm.main:Runner.spawnLogfile',
                                 'psdaq.slurm.main:Runner.restart']},
}
# The GUIs on a device stand-in that are not witnessed yet, and why (RUNBOOK §3d, R4): none since deadca (LINK_FULL).
SERVER_GUI_BLOCKERS = {}
# deadca's walk (WITNESS 'link_full'): the share of every simxpm FULL_PERIOD the DRP's link asserts full meanwhile
LINK_FULL = 0.3
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
# R8: the TPR programs of the configs, which 'daq_sim up --tpr' runs on simulated TPR cards (psdaq/psdaq/tpr/Client.cc
# with PSDAQ_SIM_TPR=<dir>: the card's register map is the file <dir>/tpr<x>, which keeps what the program writes): tprtrig
# as srcf-rix.cnf starts it (flags 'sp': procmgr adds -p <platform>, the partition its channel follows) and tpr_trigger as
# rix.py's mono_enc_trig (flags 'spu': a 'tpr' level process of the partition, its readout group from control at
# Connect), each on a card of its own (both program /dev/tpra channel 0, output 1, as the configs do).  Neither logs a
# run: while the run is Running the cycle reads each card's channel and trigger registers once a second, and coverage
# checks them against what the program's own command line programs.
# lclsBldServer (lab3-bld.cnf:52: lclsBldServer -i enp1s0f1 -r 4) is the BLD server of the configs ('kind': 'bld'): on
# each timing frame its card's channel 1 receives (here from psdaq.sim.tprframes, the card's frames of the fixed rate
# the channel selects) it sends its BLD type's packet to the type's multicast group.  The cnf line predates the -b its
# source has required since 27c997fae (which also made the groups the production 239.255.25.0-3), so it runs with
# -b ebeam, the type the usage names the default, on the loopback interface (-i lo), to a group and port off the
# production network (-a, -p: BLD_GROUP_BASE, the 'lclsbld' port of daq_sim.ports); while the run is Running the cycle
# reads its card and receives its packets (bld_receive).
TPR_PROGRAMS = {
    'tprtrig':     {'id': 'tprtrig', 'flags': 'sp', 'argv': ['-t', 'a', '-c', '0', '-o', '1', '-d', '2', '-w', '10', '-z']},
    'tpr_trigger': {'id': 'enc_trig', 'flags': 'spu',
                    'argv': ['-H', '{instr}', '-C', 'localhost', '-t', 'a', '-c', '0', '-o', '1', '-d', '2', '-w', '10']},
    'lclsBldServer': {'id': 'lclsbldsvc', 'flags': 's', 'kind': 'bld', 'dev': '-d', 'channel': 1,
                      'argv': ['-i', 'lo', '-r', '4', '-b', 'ebeam', '-a', '{bld_base}', '-p', '{bld_port}']},
}
# lclsBldServer's multicast group base on the loopback interface: administratively scoped, outside LCLS's
# 239.255.0.0/16 (as daq_sim.bld_group and simxpm's --bld-dest), so no production BLD receiver can see a packet
BLD_GROUP_BASE = '239.254.33.0'
BLD_MIN_PACKETS = 10                    # packets a 'bld' entry needs within the run
# TprReg (psdaq/psdaq/tpr/Module.hh, the card's BAR 1): TprBase at 0x80000, its 14 channels 0x1000 bytes apart
# (control, evtSel, ...), its 12 triggers from 0xA0000, 0x1000 bytes apart (control, delay, width, delayTap)
TPR_CHANNELS, TPR_TRIGGERS, TPR_STRIDE, TPR_NCHANNELS, TPR_NTRIGGERS = 0x80000, 0xA0000, 0x1000, 14, 12


def tpr_registers(path):
    """The channel and trigger registers of a TPR register map file (TprReg): {'channels': [{'control', 'evtSel'}],
    'triggers': [{'control', 'delay', 'width', 'delayTap'}]}."""
    import struct
    with open(path, 'rb') as f:
        def words(off, n):
            f.seek(off)
            b = f.read(4 * n)
            return list(struct.unpack(f'<{n}I', b)) if len(b) == 4 * n else [None] * n
        chans = [dict(zip(('control', 'evtSel'), words(TPR_CHANNELS + i * TPR_STRIDE, 2))) for i in range(TPR_NCHANNELS)]
        trigs = [dict(zip(('control', 'delay', 'width', 'delayTap'), words(TPR_TRIGGERS + i * TPR_STRIDE, 4)))
                 for i in range(TPR_NTRIGGERS)]
    return {'channels': chans, 'triggers': trigs}


def tpr_card(workdir, name):
    """The register map file of TPR program `name`'s simulated card: <workdir>/tpr/<procmgr id>/tpr<x>, x the card its
    argv names (tprtrig's and tpr_trigger's -t, lclsBldServer's -d; 'a' by default)."""
    T = TPR_PROGRAMS[name]
    opt = T.get('dev', '-t')
    return os.path.join(workdir, 'tpr', T['id'], 'tpr' + (T['argv'][T['argv'].index(opt) + 1] if opt in T['argv']
                                                          else 'a'))


def tpr_reads(card, seconds, period=1.0):
    """Read the card's registers every `period` for `seconds`: (Unix start, Unix end, reads), each read
    {'t': EPICS-epoch seconds, 'channels': [...], 'triggers': [...]} (one per change, the last always kept)."""
    out, t0 = [], time.time()
    end = t0 + seconds
    while True:
        try:
            r = tpr_registers(card)
        except OSError as ex:
            r = {'error': f'{type(ex).__name__}: {ex}'}
        r['t'] = round(time.time() - EPICS_EPOCH, 3)
        out.append(r)
        if time.time() >= end:
            break
        time.sleep(period)
    return t0, time.time(), out


def tpr_argv(name, instr, bld_base=BLD_GROUP_BASE, bld_port=None):
    """The argv procmgr's entry of TPR program `name` gives it (before procmgr's -p and -u); lclsBldServer's group
    base and port (-a, -p) are bld_base and bld_port."""
    return [a.format(instr=instr, bld_base=bld_base, bld_port=bld_port) for a in TPR_PROGRAMS[name]['argv']]


def bld_group_ok(group):
    """Whether a BLD receiver may join `group`: a multicast group in 239.0.0.0/8 outside LCLS's 239.255.0.0/16."""
    import ipaddress
    a = ipaddress.ip_address(group)
    return a in ipaddress.ip_network('239.0.0.0/8') and a not in ipaddress.ip_network('239.255.0.0/16')


def bld_receive(group, port, seconds, iface='127.0.0.1'):
    """Join multicast `group` on the interface `iface` (the loopback interface) and keep every packet that arrives on
    `port` for `seconds`: (Unix start, Unix end, packets), each (EPICS-epoch receive time, the packet's bytes).
    Refuses a group in LCLS's 239.255.0.0/16 (bld_group_ok)."""
    import socket
    if not bld_group_ok(group):
        raise ValueError(f'{group}: a BLD receiver joins only a group in 239.0.0.0/8 outside 239.255.0.0/16')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    out = []
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((group, port))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(group) + socket.inet_aton(iface))
        s.settimeout(0.2)
        t0 = time.time()
        while time.time() < t0 + seconds:
            try:
                b = s.recv(9000)
            except socket.timeout:
                continue
            out.append((round(time.time() - EPICS_EPOCH, 6), b))
        return t0, time.time(), out
    finally:
        s.close()


def bld_packet(b):
    """lclsBldServer's packet (psdaq/psdaq/app/lclsBldServer.cc): [ns, sec, pulseId, nbytes, the words its source
    fills after the time and pulse ID (payload[4] .. payload[14 + payloadWords], payloadWords = (nbytes - 96) / 4)];
    None if it is too short for that."""
    import struct
    n = (len(b) - 96) // 4
    if len(b) < 96 or (len(b) - 96) % 4 or 4 * (15 + n) > len(b):
        return None
    w = struct.unpack_from(f'<{15 + n}I', b)
    return [w[0], w[1], w[2] | (w[3] << 32), len(b), list(w[4:])]


def bld_entry(name, card, group, port, t0, t1, reads, packets):
    """The witness entry of a BLD server on a simulated TPR card ('kind': 'bld'): its card's register reads (as a 'tpr'
    entry) and the packets received on its group and port while the run ran, each [receive time, sec, ns, pulseId,
    nbytes]; 'body' the words after the time and pulse ID of the first, 'bodies' how many packets carry exactly those
    (coverage checks them, the times and the pulse IDs against the program's argv)."""
    e = tpr_entry(name, card, t0, t1, reads)
    e.update(kind='bld', group=group, port=port, packets=[], body=None, bodies=0)
    for t, b in packets:
        p = bld_packet(b)
        if p is None:
            e['problems'].append(f'a packet of {len(b)} B is not one of lclsBldServer\'s')
            continue
        ns, sec, pid, nbytes, body = p
        e['packets'].append([t, sec, ns, pid, nbytes])
        if e['body'] is None:
            e['body'] = body
        e['bodies'] += body == e['body']
    if len(e['packets']) < BLD_MIN_PACKETS:
        e['problems'].append(f'received {len(e["packets"])} packet(s) on {group}:{port} ({BLD_MIN_PACKETS} or more '
                             f'needed)')
    e['live'] = e['live'] + ([f'{group}:{port}'] if e['packets'] else [])
    e['pass'] = not e['problems']
    return e


def tpr_entry(name, card, t0, t1, reads):
    """The witness entry of a TPR program's card (R8): its register reads while the run ran; it passes if the card was
    read 2 or more times and shows a trigger output enabled (coverage checks the values against the program's argv)."""
    e = {'kind': 'tpr', 'id': TPR_PROGRAMS[name]['id'], 'card': card, 'start': round(t0 - EPICS_EPOCH, 3), 'end': round(t1 - EPICS_EPOCH, 3), 'reads': reads,
         'problems': []}
    ok = [r for r in reads if 'error' not in r]
    if len(ok) < 2:
        e['problems'].append(f'read the card {card} {len(ok)} time(s) (2 or more needed): '
                             f'{[r["error"] for r in reads if "error" in r][:1]}')
    live = sorted({f'trigger{i}' for r in ok for i, t in enumerate(r['triggers']) if (t['control'] or 0) >> 31})
    if ok and not live:
        e['problems'].append(f'no trigger output of the card {card} is enabled')
    e['live'] = live
    e['pass'] = not e['problems']
    return e


# PV-server stand-ins (R3) daq_sim up --pvservers starts, each on PVA ports of its own (so simxpm stays the
# only server on the node's search port): what the cycle reads of each while Running (a PV and a field that
# changes once a second) and the programs it stands in for, each with the PV names that program's own source
# defines (interface()).
SERVERS = {
    'simhsd': {'args': ['-P', '{pvbase}:HSD:1_DA:A', '{pvbase}:HSD:1_DA:B'], 'prefix': '{pvbase}:HSD:1_DA',
               'live': [('{pvbase}:HSD:1_DA:A:MONTIMING', 'timframecnt'), ('{pvbase}:HSD:1_DA:B:MONTIMING', 'trigcntsum')],
               'programs': ['hsdpvs', 'hsd134PVs']},
    'simtpr': {'args': ['-P', '{pvbase}:TPR'], 'prefix': '{pvbase}:TPR',
               'live': [('{pvbase}:TPR:EVTCNT', None)], 'programs': ['tprcas', 'tprioc']},
    'simdti': {'args': ['-P', '{pvbase}:DTI'], 'prefix': '{pvbase}:DTI',
               'live': [('{pvbase}:DTI:3:TimFrRate', None)], 'programs': ['dticas']},
}
# PV servers that are programs of the tree themselves (RUN rows, not stand-ins): 'daq_sim up --pvservers' starts each
# under procmgr as its config does (lab3-bld.cnf: bldcas -P DAQ:LAB2 <services>, hpsdbuscas -P DAQ:LAB2:<cp>), on PVA
# ports of its own.  They serve set values only, so the cycle's client, while the run runs, gets every name the
# program's source defines and puts each 'put' PV to its values in turn, one a second, reading it back (the server's
# own put handler posts it; hpsdbuscas's also rebuilds PAYLOAD for the new FIELDMASK, whose type ID is the mask).
# Their 'servers' entry is keyed by the program and holds its own interface.
PROGRAM_SERVERS = {
    'bldcas': {'args': ['-P', '{pvbase}', '-A', '239.254.32.1', 'HPSEX'], 'prefix': '{pvbase}:HPSEX',
               'put': ('{pvbase}:HPSEX:PORT', [11002, 11001])},
    'hpsdbuscas': {'args': ['-P', '{pvbase}:HPSCPA'], 'prefix': '{pvbase}:HPSCPA',
                   'put': ('{pvbase}:HPSCPA:HPS:FIELDMASK', [0x8001, 0x8000]),
                   'type_id': '{pvbase}:HPSCPA:PAYLOAD'},
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


def spec(name, params):
    """The qt_walk --gui spec of a passive walk of GUI `name`."""
    W = WITNESS[name]
    return {'file': W['file'], 'web': None, 'backend': 'sim-daq',
            'walk': dict({'argv': W['argv'], 'pump': 3, 'timeout': 60, 'bind_holders': True,
                          'drive': ['pump:1'] * PUMPS, 'record_calls': W.get('record_calls', [])},
                         **{k: W[k] for k in ('slurm_state', 'refresh_calls') if k in W})}


def start(workdir, name, outdir, env=None):
    """Start the passive walk of GUI `name` against the simulated DAQ in workdir; returns
    (Popen, walk path, log path, Unix start time)."""
    os.makedirs(outdir, exist_ok=True)
    sp, walk = os.path.join(outdir, f'{name}.spec.json'), os.path.join(outdir, f'{name}.walk.json')
    log = os.path.join(outdir, f'{name}.walk.log')
    with open(sp, 'w') as f:
        json.dump(spec(name, {}), f, indent=1)
    cmd = [sys.executable, '-m', 'psdaq.webgui.parity.qt_walk', '--gui', sp, '--sim-daq', workdir, '--out', walk]
    env = dict(env or os.environ, QT_QPA_PLATFORM='offscreen',
               **{k: v.format(workdir=workdir) for k, v in WITNESS[name].get('env', {}).items()})
    if 'HOME' in WITNESS[name].get('env', {}):
        os.makedirs(env['HOME'], exist_ok=True)
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
    if program == 'hsd134PVs':          # its -P is the digitizer's, the parent of the two chips' prefixes
        return hsd134pvs_names(os.path.commonprefix(prefixes).rstrip(':'))
    if program == 'tprioc':
        return tprioc_names(prefixes[0])
    if program == 'bldcas':
        return bldcas_names(args)
    if program == 'hpsdbuscas':
        return hpsdbuscas_names(prefixes[0])
    raise KeyError(program)


# hsd134PVs (psdaq/psdaq/hsd/src, C++): the PV names its sources (meson.build hsd134PVs_sources) build from -P, each
# pattern relative to the prefix; {c} is a chip, A or B ('i' loops over both, as the code does)
HSD134_PATTERNS = (
    (r'PV_ADD\s*\(\s*(\w+)\s*\)\s*;', lambda m: [f'{c}:{m.group(1).upper()}' for c in 'AB']),   # PV134Stats: STOU
    (r'STOU\(\s*pvbase_([ab])\s*\+\s*"(\w+)"\s*\)', lambda m: [f'{m.group(1).upper()}:{m.group(2).upper()}']),
    (r'NPV\(\s*\w+\s*,\s*"([\w:]+)"\s*\)', lambda m: [m.group(1)]),                            # PVCtrlsBase
    (r'\(\s*pvbase\s*\+\s*"([\w:]+)"\s*\)', lambda m: [m.group(1)]),
    (r'sprefix\s*\+=\s*\(i==0\)\s*\?\s*":(\w:\w+)"\s*:\s*":(\w:\w+)"', lambda m: [m.group(1), m.group(2)]),
    (r'sprefix\s*\+=\s*":(\w:\w+)"\s*;', lambda m: [m.group(1)]),
    (r'":"\s*\+\s*std::string\(\s*1\s*,\s*\'A\'\s*\+\s*i\s*\)\s*\+\s*":(\w+)"', lambda m: [f'{c}:{m.group(1)}' for c in 'AB']),
)


def hsd134pvs_names(prefix, repo=None):
    """The PV names hsd134PVs's C++ sources make for `hsd134PVs -P <prefix>` (read from the checkout, comments
    blanked): the patterns of HSD134_PATTERNS, with PVCtrlsBase::allocate's switch(_nchips()) taken for the 2 chips
    PV134Ctrls::_nchips() returns."""
    import re
    from psdaq.sim import coverage
    repo = repo or coverage.find_repo()
    src = os.path.join(repo, 'psdaq', 'psdaq', 'hsd')
    with open(os.path.join(src, 'meson.build')) as f:
        files = re.findall(r"'(src/[\w.]+\.cc)'", re.search(r'hsd134PVs_sources\s*=\s*\[(.*?)\]', f.read(), re.S).group(1))
    with open(os.path.join(src, 'src', 'PV134Ctrls.hh')) as f:
        nchips = re.search(r'_nchips\s*\(\)\s*\{\s*return\s+(\d+)', f.read()).group(1)
    out = set()
    for fn in files:
        with open(os.path.join(src, fn)) as f:
            text = coverage.strip_cpp_comments(f.read())
        # keep only the case of switch(_nchips()) for this chip count
        text = re.sub(r'case\s+(\d+)\s*:(.*?)break\s*;', lambda m: m.group(2) if m.group(1) == nchips else '', text,
                      flags=re.S)
        for pat, names in HSD134_PATTERNS:
            for m in re.finditer(pat, text):
                out.update(f'{prefix}:{n}' for n in names(m))
    return sorted(out)


def tprioc_names(prefix, repo=None):
    """The PV names tprioc (psdaq/psdaq/app/tprca.cc, meson.build: executable('tprioc', 'tprca.cc')) makes for
    `tprioc -n <prefix>`: TprControl's to_name(name, "...") under the prefix, and ChannelControl's under
    <prefix>:CH<i> for each of TprBase::NCHANNELS channels (psdaq/psdaq/tpr/Module.hh), read from the checkout
    with comments blanked."""
    import re
    from psdaq.sim import coverage
    repo = repo or coverage.find_repo()
    src = os.path.join(repo, 'psdaq', 'psdaq')
    with open(os.path.join(src, 'app', 'meson.build')) as f:
        files = re.findall(r"'([\w.]+\.cc)'", re.search(r"executable\(\s*'tprioc'\s*,(.*?)include_directories",
                                                       f.read(), re.S).group(1))
    with open(os.path.join(src, 'tpr', 'Module.hh')) as f:
        nchan = int(re.search(r'NCHANNELS\s*=\s*(\d+)', f.read()).group(1))
    out = set()
    for fn in files:
        with open(os.path.join(src, 'app', fn)) as f:
            text = coverage.strip_cpp_comments(f.read())
        chan = re.search(r'class\s+ChannelControl\b(.*?)class\s+TprControl\b', text, re.S).group(1)
        top = text[text.index('class TprControl'):]
        ext = r'to_name\(\s*name\s*,\s*"(\w+)"\s*\)'
        out.update(f'{prefix}:{x}' for x in re.findall(ext, top))
        out.update(f'{prefix}:CH{i}:{x}' for x in re.findall(ext, chan) for i in range(nchan))
    return sorted(out)


def bldcas_names(args):
    """The PV names psdaq/psdaq/cas/bldcas.py serves for `bldcas <args>`: its main() builds its table and hands
    it to PVAServer.createPV, here a stand-in that keeps the names and serves nothing (as tprcas_names)."""
    import contextlib
    import io
    import sys as _sys
    from psdaq.cas import bldcas
    got = []

    class Keep:
        def __init__(self, *a, **k):
            pass

        def createPV(self, pfx, pvdb):
            got.extend(pfx + k for k in pvdb)

        def forever(self):
            pass
    argv, orig = _sys.argv, bldcas.PVAServer
    try:
        _sys.argv, bldcas.PVAServer = ['bldcas'] + list(args), Keep
        with contextlib.redirect_stdout(io.StringIO()):     # it prints its table
            bldcas.main()
    finally:
        _sys.argv, bldcas.PVAServer = argv, orig
    return sorted(got)


def hpsdbuscas_names(prefix):
    """The PV names psdaq/psdaq/cas/hpsdbuscas.py serves for `hpsdbuscas -P <prefix>`: its PVAServer adds them to
    its StaticProvider, here one that only keeps the names."""
    import contextlib
    import io
    from psdaq.cas import hpsdbuscas

    class Names:
        def __init__(self, *a):
            self.names = []

        def add(self, name, pv):
            self.names.append(name)

        def remove(self, name):
            self.names.remove(name)
    orig = hpsdbuscas.StaticProvider
    try:
        hpsdbuscas.StaticProvider = Names
        with contextlib.redirect_stdout(io.StringIO()):     # it prints the payload's ID
            srv = hpsdbuscas.PVAServer('hpsdbuscas', prefix + ':')
    finally:
        hpsdbuscas.StaticProvider = orig
    return sorted(srv.provider.names)


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


def program_server_prepare(name, params, port):
    """As server_prepare, for a PROGRAM_SERVERS program: (args, {name: the PV names its source defines}, a client
    context that searches only its ports)."""
    args = [a.format(**params) for a in PROGRAM_SERVERS[name]['args']]
    return args, {name: interface(name, args)}, pva_context(port)


def program_server_entry(name, params, port, seconds, period=1.0, prepared=None):
    """The 'servers' witness entry of a PROGRAM_SERVERS program, read while the run runs: its interface (every
    name its source defines, got once from it), then, once a second for `seconds`, its 'put' PV read, and put to
    the next of its values; 'reads' holds the texts read back, 'type_ids' the 'type_id' PV's structure ID at each
    read.  It passes if every name is served and the put PV read back 2 or more distinct numbers."""
    S = PROGRAM_SERVERS[name]
    args, defined, ctx = prepared or program_server_prepare(name, params, port)
    e = {'args': args, 'port': port, 'prefix': S['prefix'].format(**params), 'interfaces': {}, 'reads': [],
         'problems': [], 'program': True}
    t0 = time.time()
    names = defined[name]
    got = ctx.get(names, timeout=5.0, throw=False)
    missing = [n for n, v in zip(names, got) if isinstance(v, Exception)]
    e['interfaces'][name] = {'defined': len(names), 'served': len(names) - len(missing), 'missing': missing}
    if missing:
        e['problems'].append(f'{name} does not serve {len(missing)} of its {len(names)} PVs, e.g. {missing[:3]}')
    pv, values = S['put'][0].format(**params), list(S['put'][1])
    tid = S['type_id'].format(**params) if S.get('type_id') else None
    vals, ids, k = [], [], 0
    end = time.time() + seconds
    while True:
        try:
            v = ctx.get(pv, timeout=2.0)
            text = f'{float(v["value"] if hasattr(v, "getID") else v):g}'   # unwrapped, or a Value once put
        except Exception as ex:
            text = f'error {type(ex).__name__}'
        if not vals or vals[-1] != text:
            vals.append(text)
        if tid:
            try:
                ids.append(ctx.get(tid, timeout=2.0).getID())
            except Exception as ex:
                ids.append(f'error {type(ex).__name__}')
        if k < len(values):
            try:
                ctx.put(pv, values[k], timeout=2.0)
            except Exception as ex:
                e['problems'].append(f'put {pv} = {values[k]}: {type(ex).__name__}: {ex}')
            k += 1
        if time.time() >= end and k >= len(values):
            break
        time.sleep(period)
    e['start'], e['end'] = round(t0 - EPICS_EPOCH, 3), round(time.time() - EPICS_EPOCH, 3)
    e['reads'] = [{'name': pv, 'values': vals}]
    if tid:
        e['type_ids'] = ids
    e['live'] = [pv] if len(numbers(vals)) >= 2 else []
    if not e['live']:
        e['problems'].append(f'{pv} did not read back 2 or more distinct numbers ({vals})')
    e['pass'] = not e['problems']
    return e


def numbers(values):
    from psdaq.sim.coverage import numbers as n
    return n(values)


def slurm_refreshes(walk):
    """R5: [{'t': EPICS-epoch seconds, 'rows': [[ID, status], ...]}] of a walk's recorded refreshes (its first
    table's first two columns: daqstat's ID and Status)."""
    out = []
    for r in walk.get('refreshes') or []:
        tables = r.get('tables') or [[]]
        rows = [[str(c[0]), str(c[1] or '').strip()] for c in tables[0] if len(c) >= 2 and c[0]]
        out.append({'t': round(r['t'] - EPICS_EPOCH, 3), 'rows': rows})
    return out


def squeue_read(state, user=None):
    """One squeue read of simslurm's jobs, made apart from the GUI (the cycle's own call of simslurm.run, as
    daqmgr's Runner calls squeue): {'t': EPICS-epoch seconds, 'jobs': {comment: state}}."""
    from psdaq.sim import simslurm
    rc, out, err = simslurm.run(['squeue', '-u', user or os.environ.get('USER', ''), '-h', '-o', '%k|%T'], state)
    jobs = dict(line.split('|', 1) for line in out.splitlines() if '|' in line) if rc == 0 else {}
    return {'t': round(time.time() - EPICS_EPOCH, 3), 'jobs': jobs}


def entry(name, walk_path, code, t0, t1, prefix, params, slurm=None):
    """The witness entry of one GUI's walk (slurm, for R5: {'prefix': daqmgr's job comment prefix, 'reads':
    [squeue_read(), ...]})."""
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
    if WITNESS[name].get('kind') == 'slurm':      # R5: the table at each refresh, and the cycle's squeue reads
        e.update(kind='slurm', comment_prefix=(slurm or {}).get('prefix'), squeue=(slurm or {}).get('reads', []),
                 refreshes=slurm_refreshes(walk))
        from psdaq.sim.coverage import slurm_matched
        live, why = slurm_matched(e)
        if len(live) < 2:
            e['problems'].append(f'{len(live)} refreshes showed what squeue said (2 or more needed): {why}')
        live = [f'refresh {r["t"]:.3f}' for r in live]
    elif WITNESS[name].get('kind') == 'procmgr':
        e['kind'] = 'procmgr'
        e['reads'] = table_reads(walk)
        live = [r['name'] for r in e['reads'] if r['values'][-1:] == ['RUNNING']]
        if not live:
            e['problems'].append('its table showed no process RUNNING')
    elif WITNESS[name].get('server'):   # R4: the PVs of a device stand-in, one read per widget
        server = WITNESS[name]['server']
        sprefix = (WITNESS[name].get('prefix') or SERVERS[server]['prefix']).format(**params)
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
