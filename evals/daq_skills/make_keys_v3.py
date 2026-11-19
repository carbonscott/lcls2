"""Write keys_v3.json: the fact keys that score.py compares reports with.

    python3 make_keys_v3.py [--check]

One key per scored case of catalog.json (sets core and full; disputed cases are left out).
Each key holds the facts a report must state, each checked on its own:

  launches      the keyed launch(es): start stamp, log files, first and last log line.
                The launch fact is scored only where the pool holds many launches (tier 3);
                'located' (does the report name the launch?) is reported for every case.
  component     the first failing component: a name, aliases, and 'not' (components a
                report may wrongly blame, e.g. the one control names).
  stage         the transition or state in which it first failed, with aliases.
  mechanism     the only judged fact: a closed list of accepted statements and of
                near-misses (statements that sound close but are incomplete or wrong).
  benign        for healthy cases: known benign lines (the double free at exit, upstream
                #134, ...), so a report can be clean, benign-defect-noted or a false alarm.

Where the keys come from: launches from the bundled pools' pool.json (data/pools.tar.gz);
components, stages and mechanisms from catalog.json's keys, rewritten by hand below as
statements after reading the logs of each pool.  No agent report was read to write them.
'Judgment' notes in a key say where the hand-writing chose between two readings.

--check exits 1 when keys_v3.json differs from what this script writes (a unit test runs it).
Standard library only.
"""

import argparse
import json
import os
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harvest import pool_id  # noqa: E402

VERSION = 3

# ---------------------------------------------------------------------------
# components: name, aliases, and components a report might wrongly blame

DRP_NOT = ['teb0', 'meb0', 'control', 'control.log', 'shmc0']


def comp(name, aliases=(), not_=DRP_NOT):
    al = [name] + [a for a in aliases if a != name]
    if '_' in name and name.rsplit('_', 1)[1].isdigit():
        base = name.rsplit('_', 1)[0]
        al += ['drp/' + name, base + ' DRP', name + ' DRP']
    return {'name': name, 'aliases': sorted(set(al), key=al.index), 'not': list(not_)}


# ---------------------------------------------------------------------------
# stages

STAGES = {
    'configure': ['configure', 'configuration', 'configuring', 'configured', 'config', 'Configure transition', 'configure phase 1',
                  'phase 1 of configure', 'connected to configured', 'connected->configured'],
    'connect': ['connect', 'connecting', 'connect transition', 'allocated to connected', 'allocated->connected'],
    'alloc': ['alloc', 'allocate', 'allocation', 'allocating', 'alloc transition'],
    'startup': ['alloc', 'allocate', 'allocation', 'start', 'startup', 'start-up', 'start up', 'launch', 'init',
                'initialisation', 'initialization', 'tt_init', 'rollcall', 'roll call', 'before rollcall', 'process start'],
    'running': ['running', 'run', 'enable', 'enabled', 'after enable', 'during the run', 'while running', 'data taking',
                'first events', 'L1Accept', 'L1Accepts', 'running state'],
    'idle-after-unconfigure': ['connected', 'connected state', 'unconfigure', 'after unconfigure', 'idle', 'disconnect',
                               'between cycles', 'between runs', 'unconfigured'],
    'beginrun': ['beginrun', 'begin run', 'begin-run', 'BeginRun', 'start of the run', 'start of run', 'run start'],
}


def stage(name, extra=(), note=None):
    al = STAGES[name] + [e for e in extra if e not in STAGES[name]]
    d = {'name': name, 'aliases': al}
    if note:
        d['judgment'] = note
    return d


# ---------------------------------------------------------------------------
# mechanism families.  Statements are written to be compared with one sentence of a
# report; the component is named where it is part of the mechanism.

def m_register(c, reg, tr):
    short = reg.split('.')[-1]
    if short == 'Enable_0':                          # reg-alloc-fakecam: rogue names the shared block, Length_0
        short = 'Enable_0 (its block, as rogue reports it: TDetSemi.Length_0)'
    return {
        'summary': '%s aborted during %s: a register write failed its verify (the value read back did not match '
                   'the value written), register %s' % (c, tr, reg),
        'accepted': [
            'A register write failed its verify: the value read back from the device did not match the value written '
            '(rogue "Verify error" / Block::checkTransaction, Got ... Exp ...).',
            'Writing register %s (%s) failed: its readback did not match what was written.' % (short, reg),
            'A write to the named register %s failed in rogue (GeneralError / Verify error), the configuration script '
            'raised a python error and the process aborted.' % short,
            'The device read back a different value for register %s than was written (Got ..., Exp ...), so the %s step '
            'failed.' % (short, tr),
        ],
        'near_miss': [
            '%s did not respond to %s / control timed out waiting for it, with no register or readback failure named.' % (c, tr),
            '%s raised a python error, crashed or aborted (signal 6) during %s, with no register write or readback '
            'failure named.' % (c, tr),
            'A hardware, firmware or link problem with the device, with no register write-verify failure named.',
            'A configuration value was wrong or out of range, with no failed register write or readback named.',
        ],
        'judgment': 'Naming the register and saying its write failed counts as the mechanism even without the word '
                    '"verify"; a python error or abort without the register does not.',
    }


M_TYPEERROR = {
    'summary': "tt_0 crashed at startup in tt_init with TypeError: __init__() got an unexpected keyword argument 'size', "
               "so it never answered rollcall and alloc failed with 'at least one DRP is required'",
    'accepted': [
        "tt_0 crashed at startup with a Python TypeError (__init__() got an unexpected keyword argument 'size'), before "
        "rollcall.",
        "A TypeError (unexpected keyword argument 'size') in the detector's initialisation code (surf/rogue flash "
        "classes, a software version mismatch) killed the DRP at startup, so it never joined rollcall and alloc failed.",
    ],
    'near_miss': [
        "tt_0 did not respond to rollcall / was missing at alloc, so alloc failed with 'at least one DRP is required', "
        "with no TypeError named.",
        'tt_0 crashed or raised a python error at startup, with no TypeError or unexpected keyword argument named.',
        'A configuration or hardware problem stopped tt_0 from starting, with no TypeError named.',
    ],
}

M_BADNAME = {
    'summary': "tt_0 aborted during configure with '*** Error: illegal XtcData::Name: "
               "expert.ClinkFeb.ClinkTop.ClinkCh.UartPiranha4.ROI[0]. Aborting.': its configuration carries bracketed "
               "field names (ROI[0], ROI[1], SAD[2]) that are not legal XTC names",
    'accepted': [
        "tt_0 aborted in configure on '*** Error: illegal XtcData::Name: ...UartPiranha4.ROI[0]'.",
        'A configuration field name with brackets (ROI[0], ROI[1], SAD[2]) is not a legal XTC name, so writing the '
        'configuration into the data stream aborted the DRP (signal 6).',
    ],
    'near_miss': [
        'tt_0 did not respond to configure / control timed out after 60 s, with no illegal-name error named.',
        'tt_0 crashed or aborted (signal 6) during configure, with no illegal XtcData::Name named.',
        'The Piranha4 camera rejected the ROI setting, or its serial (UART) setup failed.',
        'tt_0 hung while configuring the camera ROI.',
    ],
}


def m_hang(c, where, extra_near=()):
    return {
        'summary': '%s received configure, %s, then went silent with no error of its own and never replied; control '
                   'timed out after 60 s' % (c, where),
        'accepted': [
            '%s hung in configure: it went silent (%s) with no error of its own and never replied, so control timed '
            'out after 60 s.' % (c, where),
            '%s stopped responding (stalled, froze, got stuck) during configure without logging an error or crashing.' % c,
            '%s stayed alive but never finished configure; its log just stops with no error.' % c,
        ],
        'near_miss': [
            'Control reports that %s did not respond to configure (a 60 s timeout), and nothing is said about %s itself '
            'stalling or logging no error.' % (c, c),
            '%s crashed, aborted or was killed during configure.' % c,
        ] + list(extra_near),
        'judgment': 'For a hang the mechanism is the hang itself: "stopped responding with no error of its own" passes; '
                    "control's timeout message alone is a near-miss.",
    }


def m_kill(c, when, extra_acc=(), extra_near=(), timeout_near=None):
    """A process killed from outside.  timeout_near replaces the first near-miss (a bare timeout) where the key
    accepts a stall of the process too."""
    return {
        'summary': '%s was killed by signal 9 (SIGKILL, from outside) %s, with no error of its own' % (c, when),
        'accepted': [
            '%s was killed by signal 9 (SIGKILL) %s.' % (c, when),
            '%s died abruptly %s (killed from outside, signal 9) with no error of its own; the other processes failed '
            'because it was gone.' % (c, when),
        ] + list(extra_acc),
        'near_miss': [
            timeout_near or '%s and/or other processes did not respond to a transition (a timeout), with no death of %s named.' % (c, c),
            '%s crashed (segfault or abort, its own error) %s.' % (c, when),
            'teb0 (or another process) lost its connection to %s and aborted, with nothing said about why the link '
            'dropped.' % c,
        ] + list(extra_near),
    }


M_PV = {
    'summary': 'pvcam_0 (drp_pva) failed phase 1 of configure because its EPICS PV DAQ:SIM:CAM:IMAGE never connected '
               "('PV DAQ:SIM:CAM:IMAGE hasn't connected', 'Failed to get parameters for PV DAQ:SIM:CAM:IMAGE')",
    'accepted': [
        "pvcam_0's source PV DAQ:SIM:CAM:IMAGE never connected (\"hasn't connected\" / \"Failed to get parameters for PV "
        "DAQ:SIM:CAM:IMAGE\"), so configure phase 1 failed.",
        'The EPICS/PVA PV that the PVA detector reads (DAQ:SIM:CAM:IMAGE) was not served or not reachable, so the '
        'detector could not get its parameters and failed configure.',
    ],
    'near_miss': [
        "pvcam_0 reported 'Phase 1 error in Detector::configure()', with no PV named.",
        "The ConfigDB lookup failed ('get_configuration: No device pvcam_0' / 'Internal error fetching detector "
        "configuration'), so configure failed.",
        'teb0/meb0 lost connection with a DRP, or encoder_0 crashed with terminate(), and that made configure fail.',
    ],
}


def m_connect(link, other, port, wrong_link):
    return {
        'summary': 'At the connect transition pvcam_0 (drp_pva) could not open its libfabric link to %s: \'Error connecting '
                   'to 127.0.0.1:%s ...: fi_eq_sread: Interrupted system call(-4)\' -> \'%sContributor connect failed\''
                   % (other, port, link),
        'accepted': [
            "pvcam_0's %sContributor connect to %s failed at the connect transition ('%sContributor connect failed')."
            % (link, other, link),
            "pvcam_0 could not open its libfabric link to %s ('Error connecting to 127.0.0.1:%s', fi_eq_sread: "
            "Interrupted system call, EINTR)." % (other, port),
        ],
        'near_miss': [
            "Connect failed ('connect failed to change state'), with no failing link to %s named." % other,
            "pvcam_0's link to %s (the %sContributor) failed." % (wrong_link, 'Teb' if link == 'Meb' else 'Meb'),
            "meb0, teb0 or another process reported a connect error (e.g. 'Error in MEB connect()', 'Failed to accept "
            "connection'), and that is given as the cause.",
            'A network or port problem, with no failing pvcam_0 link named.',
        ],
    }


M_WAVE8 = {
    'summary': "wave8_0 failed in configure: wave8_config -> configure_trigger_delay raised ValueError('TriggerDelay(ns) "
               "too small') because the IOC-managed controls trigger delay could not be read (the simulated IOC serves no "
               "...EvrV2TriggerReg[0]:Delay PV, reads None / 0); the DRP aborted (python error, signal 6)",
    'accepted': [
        "wave8_0's configure raised ValueError('TriggerDelay(ns) too small') in configure_trigger_delay.",
        'The controls trigger delay could not be read from the IOC (its PV is not served / reads None or 0), so the '
        'computed trigger delay was too small and configure raised an error.',
        'The trigger delay configuration was invalid (too small / zero) and the wave8 configure code rejected it.',
    ],
    'near_miss': [
        'wave8_0 did not respond to configure / control timed out, with no trigger-delay error named.',
        'wave8_0 raised a python error or aborted (signal 6) during configure, with no trigger-delay error named.',
        'A register write-verify (readback) failure on a TriggerDelay register.',
    ],
}

M_JF_READBACK = {
    'summary': "jungfrau_0 failed configure phase 1: the exposure-time readback check failed ('Failed readback check of "
               "exposure time for module 0: 0.000020 [0.000010]': 20 us read back where 10 us was set), so 'Failed to "
               "configure 1 of 1 Jungfrau modules'",
    'accepted': [
        "jungfrau_0's readback check of the module's exposure time failed (set 10 us, read back 20 us: 'Failed readback "
        "check of exposure time for module 0').",
        'The Jungfrau module did not take the requested exposure time (its readback differed), so configuring the module '
        'failed.',
    ],
    'near_miss': [
        "jungfrau_0 reported 'Phase 1 error in Detector::configure()' or 'Failed to configure 1 of 1 Jungfrau modules', "
        'with no readback or exposure-time failure named.',
        'teb0 lost connection with a DRP / did not respond to disconnect, given as the cause.',
        'The double free at shutdown, or the unpinned-workers / SMT warning, given as the cause.',
    ],
}

M_OVERFLOW = {
    'summary': "Immediately after Enable the DRP opal_0 hit '<C> TebContributor::_post: _pending queue overflow' and "
               'aborted (signal 6); teb0 then lost its DRP link and aborted; disable later timed out',
    'accepted': [
        "Right after enable opal_0 hit 'TebContributor::_post: _pending queue overflow' and aborted.",
        "opal_0's queue of batches pending for the TEB (TebContributor _pending queue) overflowed at the start of the run, "
        'which killed the DRP.',
    ],
    'near_miss': [
        'opal_0 and teb0 did not respond to disable, with no queue overflow named.',
        'teb0 lost connection with a DRP and aborted, given as the cause.',
        'opal_0 crashed or aborted after enable, with no queue overflow named.',
    ],
}

M_CUDA = {
    'summary': "Right after Enable the GPU DRP fakecam_0 logged 'cudaErrorIllegalAddress (700): an illegal memory access "
               "was encountered' (drpGpu/MemPool.cc) and processed nothing further; disable phase 2 never completed",
    'accepted': [
        "After enable the GPU DRP fakecam_0 hit CUDA errors ('cudaErrorIllegalAddress (700): an illegal memory access was "
        "encountered') and stopped processing.",
        'An illegal memory access on the GPU (CUDA error 700 in drpGpu MemPool) broke the DRP pipeline, so the disable '
        'transition never got through.',
    ],
    'near_miss': [
        "fakecam_0 did not respond to disable phase 2, with no CUDA error named.",
        "The 'double free or corruption' crash at shutdown, given as the cause.",
        'The GPU DRP stalled or hung during the run, with no CUDA error named.',
    ],
}

M_JF_PACKETS = {
    'summary': "While running, the jungfrau module at 127.0.0.1:31054 stopped delivering its UDP data: from frame 1342 "
               "jungfrau_0 logged 'sent 0 of 128 packets', 'Missing data' and 'Out-of-Order data'; the Disable "
               'transition was queued behind those frames, so disable phase 2 timed out',
    'accepted': [
        "While running, the Jungfrau module stopped sending its UDP packets ('sent 0 of 128 packets', 'Missing data', "
        "'Out-of-Order data' from frame 1342).",
        'jungfrau_0 lost the detector data stream (missing/out-of-order packets from the module), and disable phase 2 '
        'was stuck behind those incomplete frames.',
    ],
    'near_miss': [
        'jungfrau_0 did not respond to disable phase 2, with no missing packets or data named.',
        'The double free at shutdown, given as the cause.',
        'jungfrau_0 hung or was slow at disable, with no missing data named.',
    ],
}

M_MAXENTRIES = {
    'summary': "The GPU DRP epixuhremu_0 aborted during configure: 'TebContributor::configure(): maxEntries (64) must "
               "divide evenly into numBuffers (16)' (started with dmaBufCount=16, fewer buffers than the 64-entry TEB "
               "batch); teb0's 'Failed to configure' is a consequence",
    'accepted': [
        "epixuhremu_0 aborted in configure on 'TebContributor::configure(): maxEntries (64) must divide evenly into "
        "numBuffers (16)'.",
        'The DRP was started with too few DMA buffers (dmaBufCount=16) for the 64-entry TEB batch, so its TEB '
        'contributor refused to configure and the process aborted.',
    ],
    'near_miss': [
        "teb0 failed to configure ('Phase 1 error: Failed to configure', 'Failed synchronize Begin with DRP', 'Link ID 0 "
        "is disconnected'), given as the cause.",
        "epixuhremu_0's timing link was still down after ConfigLclsTimingV2().",
        'epixuhremu_0 crashed or aborted during configure, with no maxEntries/numBuffers mismatch named.',
    ],
}

M_KEYERROR = {
    'summary': "Non-fatal control error at beginrun: control logged \"KeyError: 'monitor'\" while building run parameters "
               "(the per-process 'monitor' key is missing because this session never issued selectplatform before alloc), "
               "so only 1 run parameter was recorded and monitor_info was empty; the run itself was not affected",
    'accepted': [
        "control hit KeyError: 'monitor' at beginrun while building the run parameters.",
        "Control's collection state lacked the per-process 'monitor' key (no selectplatform before alloc), so beginrun "
        "recorded only 1 run parameter and sent an empty monitor_info.",
    ],
    'near_miss': [
        "fakecam_0's output directory stat error (No such file or directory), given as the cause.",
        "'ami NOT supported in absence of MEB', given as the cause.",
        'A control error at beginrun, with no KeyError or missing monitor key named.',
    ],
}


def m_meb_killed():
    return m_kill('meb0', 'while the DAQ was running', extra_acc=[
        "meb0 (the monitoring event builder) disappeared during the run (SIGKILL), after which the DRPs failed on their MEB "
        "links ('Error receiving transition buffer index from MEB ID 0') and aborted."],
        extra_near=["The DRPs aborted with 'Error receiving transition buffer index from MEB ID 0 needed for SlowUpdate' "
                    '(MebContributor::post), given as the cause.',
                    'All six clients did not respond to disable, with no death of meb0 named.'])


# ---------------------------------------------------------------------------
# benign defects (healthy cases).  'when' is where they appear.

B_DOUBLE_FREE = {'id': 'double-free-exit', 'desc': "a DRP aborts at shutdown with 'free(): double free detected in tcache "
                 "2' (signal 6), after the run ended (upstream #134)",
                 'aliases': ['double free', 'double-free', 'tcache', '#134', 'issues/134', 'crash at shutdown',
                             'crashed at shutdown', 'crash at exit', 'signal 6 at shutdown', 'abort at shutdown']}
B_RTPRIO = {'id': 'rtprio', 'desc': "'<C> Inadequate RTPRIO limit: got 0, require 99' at startup in every process",
            'aliases': ['RTPRIO', 'real-time priority', 'realtime priority']}
B_AMI = {'id': 'ami-no-meb', 'desc': "control '<W> ami NOT supported in absence of MEB'", 'aliases': ['ami NOT supported', 'absence of MEB']}
B_APPLANE = {'id': 'applane-lookup', 'desc': "'Lookup failed for node [AppLane]' in tt_0's configuration",
             'aliases': ['AppLane', 'Lookup failed for node']}
B_AMI_KILL = {'id': 'ami-killed-at-shutdown', 'desc': 'ami-client / ami-worker killed by signal 9, shmc0 by signal 2, at '
              'shutdown', 'aliases': ['ami-client', 'ami-worker', 'shmc0', 'signal 9']}
B_SEGV_EXIT = {'id': 'segfault-exit', 'desc': "epixm320_0 'FATAL: Segmentation Fault' after Ctrl-C at shutdown",
               'aliases': ['epixm320', 'Segmentation Fault', 'segfault']}
B_LOOKUP = {'id': 'node-lookup', 'desc': "epixquad 'WARNING: Lookup failed for node [OverSampleEn] ...'", 'aliases': ['Lookup failed', 'OverSampleEn']}
B_CONFIGDB = {'id': 'configdb-no-device', 'desc': "'get_configuration: No device <det>!' / 'Internal error fetching "
              "detector configuration' tracebacks (encoder_0, epics_0, pvcam_0)",
              'aliases': ['No device', 'Internal error fetching detector configuration', 'get_configuration', 'configdb', 'ConfigDB']}
B_PVATABLE = {'id': 'pvatable-keyerror', 'desc': "pvatable helper KeyError 'readcntsum'", 'aliases': ['readcntsum', 'pvatable']}
B_ENCTRIG = {'id': 'enc-trig-not-selected', 'desc': "control '<W> rollcall: tpr/enc_trig NOT selected for data collection'",
             'aliases': ['enc_trig', 'NOT selected']}

# ---------------------------------------------------------------------------
# the cases, by hand.  Register names come from the catalog summaries.

TT_REG = 'TimeToolKcu1500Root.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer[0].TriggerDelay'
TT = comp('tt_0', ['tt', 'timetool', 'time tool', 'drp tt', 'TimeTool DRP'])
FAKECAM_1DRP = comp('fakecam_0', ['fakecam', 'the DRP', 'detector DRP', 'DRP'])
PVCAM = comp('pvcam_0', ['pvcam', 'drp_pva', 'PV camera', 'PVA detector', 'PVA DRP'],
             not_=['teb0', 'meb0', 'control', 'encoder_0', 'epics_0', 'fakecam_0'])
NOTE_RUNSTAGE = ('The first failure is in the running state; "disable" is also accepted because the catalog key lists it '
                 'and the failure is noticed there.')


def register_case(c, reg, tr):
    return {'component': comp(c), 'stage': stage(tr), 'mechanism': m_register(c, reg, tr)}


HAND = {
    'kill-drp': {'component': FAKECAM_1DRP, 'stage': stage('running', ['disable'], NOTE_RUNSTAGE),
                 'mechanism': m_kill('fakecam_0', 'while the DAQ was running')},
    'startup-crash-tt': {'component': TT, 'stage': stage('startup'), 'mechanism': M_TYPEERROR},
    'cfg-badname-tt': {'component': TT, 'stage': stage('configure'), 'mechanism': M_BADNAME},
    'cfg-value-wave8': {'component': comp('wave8_0', ['wave8', 'drp wave8']), 'stage': stage('configure'), 'mechanism': M_WAVE8},
    'jf-readback': {'component': comp('jungfrau_0', ['jungfrau', 'jf', 'drp jungfrau', 'Jungfrau module']),
                    'stage': stage('configure'), 'mechanism': M_JF_READBACK},
    'pv-missing-pvcam': {'component': PVCAM, 'stage': stage('configure'), 'mechanism': M_PV},
    'ctl-blames-meb': {
        'component': comp('fakecam_0', ['fakecam', 'the DRP', 'detector DRP', 'DRP'], not_=['meb0', 'teb0', 'control', 'MEB', 'TEB']),
        'stage': stage('configure'),
        'mechanism': m_kill('fakecam_0', 'during the second configure', extra_acc=[
            'fakecam_0 went silent (stalled) on the second configure: it never logged receipt of configure, and was then '
            'killed (signal 9); teb0 and meb0 failed only because their link to DRP ID 0 was gone.',
            'fakecam_0 stalled, hung or stopped responding on the (second) configure: it never logged receipt of configure'
            ', whether or not its death by signal 9 is also named.',
            'The DRP fakecam_0 stopped responding / was killed during configure, so the event builders could not '
            "synchronise with DRP ID 0 ('Link ID 0 is disconnected'); control names meb0 only because its reply came first."],
            extra_near=["meb0 (or teb0) failed to configure ('Failed synchronize Begin with DRP: rc -107', 'Link ID 0 is "
                        "disconnected'), given as the cause, with nothing said about the DRP dying or stalling.",
                        'The DRP link (Link ID 0) was disconnected, with no cause on the DRP side named.'],
            timeout_near="Only control's timeout message (a process 'did not respond to configure', a transition timeout), "
                         'with nothing said about fakecam_0 itself stalling, stopping, never logging configure or dying.'),
        'judgment': 'Accepts either the SIGKILL or the stall before it (the key says both: silent, then killed).'},
    'drp-gone-cfg': {'component': FAKECAM_1DRP, 'stage': stage('configure'),
                     'mechanism': m_kill('fakecam_0', 'part-way through configure (second cycle)')},
    'drp-killed-idle': {'component': FAKECAM_1DRP,
                        'stage': stage('idle-after-unconfigure', note='Killed after unconfigure completed, before '
                                       'disconnect; the failure surfaces at disconnect, so disconnect is accepted.'),
                        'mechanism': m_kill('fakecam_0', 'after configure and unconfigure had completed (state connected)')},
    'control-keyerror': {'component': comp('control', ['control.log', 'run control', 'collection manager', 'controller',
                                                       'DAQ control'], not_=['fakecam_0', 'teb0']),
                         'stage': stage('beginrun'), 'mechanism': M_KEYERROR, 'side_issue_ok': True,
                         'judgment': 'The key itself says the run was not affected, so the keyed error may be reported as '
                                     'a non-fatal problem: a report that concludes "no failure" but names it passes.'},
    'gpu-hang-cfg': {'component': comp('jungfrau_0', ['jungfrau', 'drp_gpu', 'GPU DRP', 'jf']),
                     'stage': stage('configure'),
                     'mechanism': m_hang('jungfrau_0', 'after starting its Collector and TrgInpGen receiver threads',
                                         extra_near=["teb0's segmentation fault (Error reading Rx CQ, comp_error_dump), given "
                                                     'as the cause.',
                                                     "jungfrau_0 lost connection with the TEB ('TEB Receiver thread lost "
                                                     "connection with a TEB').",
                                                     'A GPU or CUDA error in jungfrau_0.'])},
    'teb-overflow': {'component': comp('opal_0', ['opal', 'drp/opal_0', 'the DRP', 'TebContributor']),
                     'stage': stage('running'), 'mechanism': M_OVERFLOW},
    'gpu-cuda': {'component': comp('fakecam_0', ['fakecam', 'drp_gpu', 'GPU DRP']),
                 'stage': stage('running', ['disable'], NOTE_RUNSTAGE), 'mechanism': M_CUDA},
    'jf-missing-packets': {'component': comp('jungfrau_0', ['jungfrau', 'jungfrau module', '127.0.0.1:31054', 'Jungfrau detector']),
                           'stage': stage('running', ['disable'], NOTE_RUNSTAGE), 'mechanism': M_JF_PACKETS},
    'ctl-blames-teb': {'component': comp('epixuhremu_0', ['epixuhremu', 'drp_gpu', 'gpu drp', 'epixuhr'], not_=['teb0', 'control']),
                       'stage': stage('configure'), 'mechanism': M_MAXENTRIES},
    'hang-cfg-tt': {'component': TT, 'stage': stage('configure'),
                    'mechanism': m_hang('tt_0', "while setting up its Piranha4 camera over the serial link, last line "
                                        "'sleeping for ...UartPiranha4.ROI[0]'",
                                        extra_near=["The illegal XtcData::Name on ROI[0] aborted tt_0.",
                                                    "teb0's segmentation fault on the recovery disconnect, given as the cause.",
                                                    'The double free in tt_0 at shutdown, given as the cause.'])},
    'big-pvcam': {'component': PVCAM, 'stage': stage('configure'), 'mechanism': M_PV},
    'big-tebctrb-connect': {'component': PVCAM, 'stage': stage('connect'),
                            'mechanism': m_connect('Teb', 'teb0', '40459', 'meb0')},
    'big-meb-killed': {'component': comp('meb0', ['meb', 'monReqServer', 'monitoring event builder', 'MEB'],
                                         not_=['pvcam_0', 'encoder_0', 'epics_0', 'fakecam_0', 'teb0', 'control', 'DRP', 'DRPs']),
                       'stage': stage('running'), 'mechanism': m_meb_killed()},
    'day-big-window': {'component': PVCAM, 'stage': stage('configure'), 'mechanism': M_PV},
    'day-other-error': {'component': PVCAM, 'stage': stage('connect'),
                        'mechanism': m_connect('Meb', 'meb0', '44567', 'teb0')},
    'day-startup': {'component': TT, 'stage': stage('startup'), 'mechanism': M_TYPEERROR},
    'day-window': register_case('tt_0', TT_REG, 'configure'),
    'day-window-utc': register_case('tt_0', TT_REG, 'configure'),
    'day-last-good': dict(register_case('tt_0', TT_REG, 'configure'), required_launches=['09_12:21:27'],
                          fault_launch='09_12:22:37'),
}
# the same fault asked another way ('-q') or in another pool of the same kind
HAND['kill-drp-q'] = HAND['kill-drp']
HAND['startup-crash-tt-q'] = HAND['startup-crash-tt']
HAND['big-pvcam-23'] = HAND['big-pvcam']
# every other fault case is a register case, built from the catalog in build()

# day-count: which family each failed launch belongs to (from the catalog's per-launch causes)
DAY_COUNT = {'09_11:58:38': 'badname', '09_12:06:35': 'register', '09_12:12:52': 'register', '09_12:15:15': 'typeerror',
             '09_12:22:37': 'register', '09_12:24:58': 'typeerror', '09_12:49:29': 'typeerror', '09_12:55:54': 'hang',
             '09_13:06:52': 'register'}

HEALTHY_BENIGN = {
    'healthy-tt': [B_DOUBLE_FREE, B_RTPRIO, B_AMI, B_APPLANE],
    'healthy-fakecam': [B_RTPRIO, B_AMI],
    'healthy-jungfrau': [B_DOUBLE_FREE, B_RTPRIO, B_AMI],
    'healthy-ami': [B_DOUBLE_FREE, B_AMI_KILL, B_RTPRIO],
    'day-healthy-window': [B_DOUBLE_FREE, B_SEGV_EXIT, B_LOOKUP, B_CONFIGDB, B_PVATABLE, B_ENCTRIG, B_AMI_KILL, B_RTPRIO, B_APPLANE],
    'day-healthy-late': [B_DOUBLE_FREE, B_LOOKUP, B_RTPRIO],
}


# ---------------------------------------------------------------------------


def read_pools(tgz):
    out = {}
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            parts = m.name.split('/')
            if len(parts) == 3 and parts[0] == 'pools' and parts[2] == 'pool.json':
                out[parts[1]] = json.load(t.extractfile(m))
    return out


def launch_rec(s):
    return {'prefix': s['prefix'], 'start': s['start'], 'first': s['first'], 'last': s['last'], 'files': s['files']}


def build(catalog, pools):
    cases = [c for c in catalog['cases'] if c['set'] in ('core', 'full')]
    used_pools, keys = {}, {}
    for c in cases:
        pool = pools[pool_id(c['pool'])]
        by_prefix = {s['prefix']: s for s in pool['sessions']}
        key = c['key']
        f = key.get('fault')
        k = {'id': c['id'], 'set': c['set'], 'tier': c['tier'], 'key_source': c['key_source'], 'pool': c['pool'],
             'question': c['question'], 'launch_keyed': len(pool['sessions']) > 1,
             'launches': [launch_rec(by_prefix[p]) for p in key.get('sessions') or []],
             'known_issues': key.get('known_issues') or []}
        if len(pool['sessions']) > 1:
            used_pools[c['pool']] = [[s['prefix'], s['start'], s['last']] for s in pool['sessions']]
        if not f:
            k.update(kind='healthy', benign=HEALTHY_BENIGN[c['id']])
            if not k['launches']:
                # a window: every launch inside it is healthy; 'located' is not defined
                k['window_note'] = 'no keyed launch: the question names a window whose launches were all healthy'
        elif key.get('launches'):
            fams = {'register': m_register('tt_0', TT_REG, 'configure'), 'typeerror': M_TYPEERROR, 'badname': M_BADNAME,
                    'hang': HAND['hang-cfg-tt']['mechanism']}
            stg = {'register': stage('configure'), 'typeerror': stage('startup'), 'badname': stage('configure'),
                   'hang': stage('configure')}
            k.update(kind='multi', component=TT, failed=[
                {'prefix': l['prefix'], 'family': DAY_COUNT[l['prefix']], 'stage': stg[DAY_COUNT[l['prefix']]],
                 'mechanism': fams[DAY_COUNT[l['prefix']]], 'catalog_cause': l['cause']} for l in key['launches']])
            lo, hi = '09_11:50:00', '09_13:10:00'
            k['healthy_in_window'] = [s['prefix'] for s in pool['sessions'] if lo <= s['prefix'] <= hi
                                      and s['prefix'] not in DAY_COUNT]
        else:
            h = HAND.get(c['id'])
            if h is None:                            # register cases: everything follows from the catalog
                reg = f['summary'].rsplit('(register ', 1)[1].rstrip(')')
                h = register_case(f['component'][0], reg, f['transition'][0])
            k.update(kind='fault', **{kk: v for kk, v in h.items()})
            k['side_issues_known'] = key.get('independent') or []
            if 'fault_launch' not in k and k['launches']:
                k['fault_launch'] = k['launches'][0]['prefix']
        k['catalog_summary'] = f['summary'] if f else 'NO FAULT'
        keys[c['id']] = k
    return {'version': VERSION, 'about': __doc__.split('\n\n')[2].strip(), 'tz_offset_hours': -8,
            'pools': used_pools, 'cases': keys}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--catalog', default=os.path.join(HERE, 'catalog.json'))
    ap.add_argument('--pools', default=os.path.join(HERE, 'data', 'pools.tar.gz'))
    ap.add_argument('--out', default=os.path.join(HERE, 'keys_v3.json'))
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    with open(a.catalog) as f:
        cat = json.load(f)
    text = json.dumps(build(cat, read_pools(a.pools)), indent=1) + '\n'
    if a.check:
        same = False
        if os.path.exists(a.out):
            with open(a.out) as f:
                same = f.read() == text
        print('%s is %s' % (a.out, 'up to date' if same else 'OUT OF DATE: run make_keys_v3.py'))
        return 0 if same else 1
    with open(a.out, 'w') as f:
        f.write(text)
    print('wrote %s' % a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
