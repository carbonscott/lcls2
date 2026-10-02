"""DRP configuration functions for the timetool (``lcls2_timetool.TimeToolKcu1500Root`` with a ClinkFeb camera UART).

The module keeps the root (`cl`), FEB lane/channel, readout group and last configuration
(`ocfg`) in module globals.
"""
from psdaq.configdb.get_config import get_config
from psdaq.configdb.scan_utils import *
from psdaq.cas.xpm_utils import timTxId
from .xpmmini import *
import rogue
from psdaq.utils import enable_lcls2_timetool
import lcls2_timetool
import json
import IPython
import logging

from collections import deque

pv = None
cl = None

# FEB parameters
lane = 0
chan = 0
group = None
ocfg = None

def cl_poll(uart):
    """Wait until ``uart._rx._last`` is set, then clear it; polls every 10 ms with no timeout."""
    while True:
        result = uart._rx._last
        if result is not None:
            uart._rx._last = None
            break
        time.sleep(0.01)

def tt_init(arg,dev='/dev/datadev_0',lanemask=1,xpmpv=None,timebase="186M",verbosity=0):
    """Open and enter a ``TimeToolKcu1500Root`` on `dev`, set up XpmMini timing, and return it (also stored in the global `cl`).

    If `xpmpv` is given, ``ConfigureXpmMini`` is called and a `PVCtrls` thread serving PVs under
    `xpmpv` is started; otherwise ``ConfigureXpmMini`` and ``ConfigLclsTimingV2`` are called.
    The root logger level is set to ``40 - 10*verbosity``; `arg`, `lanemask` and `timebase` are unused.
    """
    global cl

    logging.getLogger().setLevel(40-10*verbosity)

    myargs = { 'dev'         : dev,
               'pgp3'        : False,
               'pollEn'      : False,
               'initRead'    : False,
               'dataCapture' : False,
               'dataDebug'   : False,}

    cl = lcls2_timetool.TimeToolKcu1500Root(**myargs)
    cl.__enter__()

    # Open a new thread here
    if xpmpv is not None:
        cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.ConfigureXpmMini()
        pv = PVCtrls(xpmpv,cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.XpmMiniWrapper)
        pv.start()
    else:
        print('XpmMini')
        cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.ConfigureXpmMini()
        cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.ConfigLclsTimingV2()
        time.sleep(0.1)

    return cl

def tt_init_feb(slane=None,schan=None):
    """Set the global FEB `lane` and `chan` from `slane` and `schan` (converted to int) when they are not None."""
    global lane
    global chan
    if slane is not None:
        lane = int(slane)
    if schan is not None:
        chan = int(schan)

def tt_connect(cl):

    """Check the PGP link, write the timetool transmitter ID, and return ``{'paddr': rxId}``.

    `rxId` is the XpmMessageAligner 'RxId' read before ``TxId`` is set to ``timTxId('timetool')``.

    Raises
    ------
    ValueError
        If 'RxRemLinkReady' of ``PgpMon[lane]`` is not 1.
    """
    if(getattr(cl.TimeToolKcu1500.Kcu1500Hsio,'PgpMon[%d]'%lane).RxRemLinkReady.get() != 1):
        raise ValueError(f'PGP Link is down' )

    txId = timTxId('timetool')

    rxId = cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.XpmMessageAligner.RxId.get()
    cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.XpmMessageAligner.TxId.set(txId)

    d = {}
    d['paddr'] = rxId
    return d

def user_to_expert(cl, cfg, full=False):
    """Translate user settings in `cfg` into expert entries and write them into `cfg` with `update_config_entry` (types from the global `ocfg`).

    'user.start_ns' sets TriggerDelay to ``int(start_ns*1300/7000 - PartitionDelay[group]*200)`` and
    'user.gate_ns' sets ``expert.ClinkFeb.TrigCtrl.TrigPulseWidth`` to ``gate_ns*0.001``; with `full`,
    the TriggerEventBuffer 'Partition' is set to the global `group`.

    Raises
    ------
    ValueError
        If the computed TriggerDelay is negative.
    """
    global group
    global ocfg

    d = {}
    if full:
        d['expert.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer.Partition'] = group

    try:
        rawStart       = cfg['user']['start_ns']
        partitionDelay = getattr(cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.XpmMessageAligner,'PartitionDelay[%d]'%group).get()
        triggerDelay   = int(rawStart*1300/7000 - partitionDelay*200)
        print('partitionDelay {:}  rawStart {:}  triggerDelay {:}'.format(partitionDelay,rawStart,triggerDelay))
        if triggerDelay < 0:
            print('partitionDelay {:}  rawStart {:}  triggerDelay {:}'.format(partitionDelay,rawStart,triggerDelay))
            raise ValueError('triggerDelay computes to < 0')
        d['expert.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager.TriggerEventBuffer.TriggerDelay']=triggerDelay
    except KeyError:
        pass

    try:
        gate = cfg['user']['gate_ns']
        d['expert.ClinkFeb.TrigCtrl.TrigPulseWidth'] = gate*0.001
    except KeyError:
        pass

    update_config_entry(cfg,ocfg,d)

def config_expert(cl,cfg):
    """Write the values in ``cfg['expert']`` to the matching nodes below `cl`, mapping generic names to the current lane/channel.

    For example 'ClinkFeb' becomes 'ClinkFeb[<lane>]' and 'ClinkCh' becomes 'Ch[<chan>]'; values under
    '.FIR.' are parsed as hex strings. After setting a node whose path contains 'Uart' (except
    'ROI[0]', 'SAD[0]' and 'SAD[1]'), it waits for a UART reply with `cl_poll`.
    """
    global lane
    global chan

    rogue_translate = {'ClinkFeb'          :'ClinkFeb[%d]'%lane,
                       'ClinkCh'           :'Ch[%d]'%chan,
                       'TriggerEventBuffer':'TriggerEventBuffer[%d]'%lane,
                       'TrigCtrl'          :'TrigCtrl[%d]'%chan,
                       'PllConfig0'        :'PllConfig[0]',
                       'PllConfig1'        :'PllConfig[1]',
                       'PllConfig2'        :'PllConfig[2]'}

    uart = getattr(getattr(cl,'ClinkFeb[%d]'%lane).ClinkTop,'Ch[%d]'%chan).UartPiranha4

    depth = 0
    path  = 'cl'
    my_queue  =  deque([[path,depth,cl,cfg['expert']]]) #contains path, dfs depth, rogue hiearchy, and daq configdb dict tree node
    while(my_queue):
        path,depth,rogue_node, configdb_node = my_queue.pop()
        #  Replace configdb lane and febch for the physical values
        if(dict is type(configdb_node)):
            for i in configdb_node:
                #  Substitute proper pgp lane or feb channel
                if i in rogue_translate:
                    my_queue.appendleft([path+"."+i,depth+1,rogue_node.nodes[rogue_translate[i]],configdb_node[i]])
                else:
                    try:
                        my_queue.appendleft([path+"."+i,depth+1,rogue_node.nodes[i],configdb_node[i]])
                    except KeyError:
                        print('Lookup failed for node [{:}] in path [{:}]'.format(i,path))

        if('get' in dir(rogue_node) and 'set' in dir(rogue_node) and path != 'cl' ):

            #  All FIR parameters are stored in configdb as hex strings (I don't know why)
            if ".FIR." in path:
                print(path+", rogue value = "+str(hex(rogue_node.get()))+", daq config database = " +str(configdb_node))
                rogue_node.set(int(str(configdb_node),16))
            else:
                rogue_node.set(configdb_node)

            if 'Uart' in path:
                if 'ROI[0]' in path or 'SAD[0]' in path or 'SAD[1]' in path:
                    # These don't cause the send of a serial command
                    pass
                else:
                    print('sleeping for {:}'.format(path))
                    cl_poll(uart)


def tt_config(cl,connect_str,cfgtype,detname,detsegm,grp):
    """Read the configuration, apply it to the timetool, enable the trigger buffer, and return the configuration as JSON.

    Stores `grp` and the configuration in globals, applies `user_to_expert` (full), forces
    EnableTrig/DataEn True and InvCC/Blowoff False, sends an escape and the expert values to the
    camera UART, sends 'gcp' and waits for the reply, then adds 'firmwareVersion' and 'firmwareBuild'.
    """
    global group
    global ocfg
    group = grp

    cfg = get_config(connect_str,cfgtype,detname,detsegm)
    ocfg = cfg

    user_to_expert(cl,cfg,full=True)

    #  set bool parameters
    cfg['expert']['ClinkFeb']['TrigCtrl']['EnableTrig'] = True
    cfg['expert']['ClinkFeb']['TrigCtrl']['InvCC'] = False
    cfg['expert']['ClinkFeb']['ClinkTop']['ClinkCh']['DataEn'] = True
    cfg['expert']['ClinkFeb']['ClinkTop']['ClinkCh']['Blowoff'] = False

    uart = getattr(getattr(cl,'ClinkFeb[%d]'%lane).ClinkTop,'Ch[%d]'%chan).UartPiranha4

    getattr(getattr(cl,'ClinkFeb[%d]'%lane).ClinkTop,'Ch[%d]'%chan).UartPiranha4.SendEscape()

    config_expert(cl,cfg)

    #commands can be sent manually using cl.ClinkFeb0.ClinkTop.Ch0.UartPiranha4._tx.sendString('GCP')
    # GCP returns configuration summary
    uart._tx.sendString('gcp')
    cl_poll(uart)

    #cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.XpmMiniWrapper.XpmMini.HwEnable.set(True)
    getattr(cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager,'TriggerEventBuffer[%d]'%lane).MasterEnable.set(True)

    #  Capture the firmware version to persist in the xtc
    cfg['firmwareVersion'] = cl.TimeToolKcu1500.AxiPcieCore.AxiVersion.FpgaVersion.get()
    cfg['firmwareBuild'  ] = cl.TimeToolKcu1500.AxiPcieCore.AxiVersion.BuildStamp.get()

    return json.dumps(cfg)

def tt_scan_keys(update):
    """Return JSON with the entries named in the JSON `update` copied from the stored configuration (not the new values), plus derived expert entries and the 'detType:RO'-style header keys."""
    global cl
    global ocfg
    #  extract updates
    cfg = {}
    copy_reconfig_keys(cfg,ocfg, json.loads(update))
    #  Apply group
    user_to_expert(cl,cfg,full=False)
    #  Retain mandatory fields for XTC translation
    for key in ('detType:RO','detName:RO','detId:RO','doc:RO','alg:RO'):
        copy_config_entry(cfg,ocfg,key)
        copy_config_entry(cfg[':types:'],ocfg[':types:'],key)
    return json.dumps(cfg)

def tt_update(update):
    """Merge the JSON `update` into a new dict (types from the stored configuration), add the derived expert entries, write its 'expert' part to the hardware with `config_expert`, and return it as JSON with the header keys."""
    global cl
    global ocfg
    #  extract updates
    cfg = {}
    update_config_entry(cfg,ocfg, json.loads(update))
    #  Apply group
    user_to_expert(cl,cfg,full=False)
    #  Apply config
    config_expert(cl, cfg)
    #  Retain mandatory fields for XTC translation
    for key in ('detType:RO','detName:RO','detId:RO','doc:RO','alg:RO'):
        copy_config_entry(cfg,ocfg,key)
        copy_config_entry(cfg[':types:'],ocfg[':types:'],key)
    return json.dumps(cfg)

def tt_unconfig(cl):
    """Set 'MasterEnable' of ``TriggerEventBuffer[lane]`` to False."""
    getattr(cl.TimeToolKcu1500.Kcu1500Hsio.TimingRx.TriggerEventManager,'TriggerEventBuffer[%d]'%lane).MasterEnable.set(False)

