"""DRP functions for a timing-only detector using an ``l2si_drp.DrpTDetRoot`` (KCU1500 or C1100 board).

State (device, lane mask, timebase, root) is kept in the module dict `args`, and a module
`Barrier` coordinates processes sharing the board.
"""
from psdaq.utils import enable_l2si_drp
import l2si_drp
from psdaq.configdb.barrier import *
from psdaq.cas.xpm_utils import timTxId
import rogue
import time
import json
import logging

barrier_global = Barrier()
args = {}
#logging.basicConfig(level=logging.INFO)

def detect_C1100():
    ''' Detect if the board is a C1100 by reading /proc/datadev_0 '''
    file_datadev='/proc/datadev_0'
    isC1100 = False
    try:
        with open(file_datadev, 'r', encoding='utf-8') as file:
            for line in file:
                if 'Build String' in line:
                    isC1100 = 'C1100' in line
                    break
        return isC1100

    except FileNotFoundError:
        logging.error(f"Error: File '{file_datadev}' not found.")
        return False
    except Exception as e:
        logging.error(f"Error reading file: {e}")
        return False

def dumpTiming(tim):
    """Log (at warning level) the 'FidCount', 'RxRstCount', 'RxDecErrCount' and 'RxDspErrCount' values of timing receiver `tim`."""
    logging.warning(f'FidCount  : {tim.FidCount.get()}')
    logging.warning(f'RxRstCount: {tim.RxRstCount.get()}')
    logging.warning(f'RxDecErrs : {tim.RxDecErrCount.get()}')
    logging.warning(f'RxDspErrs : {tim.RxDspErrCount.get()}')

def xpmdet_init(dev='/dev/datadev_0',lanemask=1,timebase="186M",verbosity=0):
    """Open and enter a ``DrpTDetRoot`` on `dev` (with C1100 options if `detect_C1100` finds one), store settings in `args`, and return the root.

    ``args['root']`` is set to ``root.PcieControl.DevPcie`` and ``args['core']`` to whether
    'DRIVER_TYPE_ID_G' is 0. `verbosity` is unused.
    """
    global args
    logging.info('xpmdet_init')

    args["dev"]     =dev
    args["timebase"]=timebase
    args["lanemask"]=lanemask

    if (detect_C1100()):
       # print("Board Detected C1100")
        root = l2si_drp.DrpTDetRoot(pollEn=False,devname=dev,boardType='VariumC1100',qsa=False, xvcPort=None)
        root.__enter__()
        logging.info("Board Detected C1100")

    else:
       # print("Board Detected KCU1500")
        root = l2si_drp.DrpTDetRoot(pollEn=False,devname=dev)
        root.__enter__()
        logging.info("Board Detected KCU1500")

    args['root'] = root.PcieControl.DevPcie
    args['core'] = root.PcieControl.DevPcie.AxiPcieCore.AxiVersion.DRIVER_TYPE_ID_G.get()==0
#    print("init done")
##  Moved to connectionInfo so supervisor can execute it only once
#    logging.info('Reset timing data path')
#    dumpTiming(root.PcieControl.DevKcu1500.TDetTiming.TimingFrameRx)
#    root.PcieControl.DevKcu1500.TDetTiming.TimingFrameRx.C_RxReset()
#    time.sleep(0.1)
#    root.PcieControl.DevKcu1500.TDetTiming.TimingFrameRx.ClearRxCounters()

    return root

# called on alloc
def xpmdet_connectionInfo(alloc_json_str):
   # print("xpmdet_connectionInfo")
    """Set up the barrier from the allocate JSON and, in the supervisor, prepare the timing link; return ``{'paddr': RxId}``.

    The supervisor clears counters, reprograms the Si570 and resets the receiver if
    ``refClockRate()`` is outside 180-190 (186M) or 115-125 (119M), writes ``timTxId('tdet')`` to TxId,
    disables and resets the 8 trigger event buffers, and retries an RxPllReset if RxId is 0,
    0xffffffff or has low byte > 15. All processes then wait on the barrier and read RxId.

    Raises
    ------
    RuntimeError
        If RxId is still illegal after the retry (supervisor only).
    """
    root = args['root']

    xma = root.TDetTiming.TriggerEventManager.XpmMessageAligner
   # time.sleep(1)

    alloc_json = json.loads(alloc_json_str)
    supervisor,nworker = supervisor_info(alloc_json,args['dev'])
    logging.info(f'xpmdet supervisor: {supervisor}, nworkers: {nworker}')
    barrier_global.init(supervisor,nworker)

    if barrier_global.supervisor:

        tim = root.TDetTiming.TimingFrameRx
        dumpTiming(tim)
        time.sleep(0.1)
        tim.ClearRxCounters()

        if args["timebase"]=="186M":
            clockrange = (180.,190.)
        elif args["timebase"]=="119M":
            clockrange = (115.,125.)
        else:
            clockrange = None

        if clockrange is not None:
            if True:
#            if args['core']:
                # check timing reference clock, program if necessary
                rate = root.TDetTiming.refClockRate()

                if (rate < clockrange[0] or rate > clockrange[1]):
                    root.I2CBus.programSi570(119. if args["timebase"]=="119M" else 1300/7.)
                    tim.RxPllReset.set(1)
                    tim.RxPllReset.set(0)
                    time.sleep(0.0001)
                    dumpTiming(tim)
                    tim.C_RxReset()
                    time.sleep(0.1)
                    tim.ClearRxCounters()
            else:
                logging.warning('Supervisor is not I2cBus manager')

        txId = timTxId('tdet')
        xma.TxId.set(txId)

        rxId = xma.RxId.get()
        logging.info('rxId {:x}'.format(rxId))

        #  Disable all timing links
        for i in range(8):
            teb = getattr(root.TDetTiming.TriggerEventManager,f'TriggerEventBuffer[{i}]')
            teb.MasterEnable.set(0)
            teb.ResetCounters()
            teb.FifoReset()
        xpmdet_unconfig()

        rxId = xma.RxId.get()
        logging.info('rxId {:x}'.format(rxId))

        if (rxId==0 or rxId==0xffffffff or (rxId&0xff)>15):
            logging.warning(f"XPM Remote link id register illegal value: 0x{rxId:08x}. Trying RxPllReset.");
            tim = root.TDetTiming.TimingFrameRx
            tim.RxPllReset.set(1)
            tim.RxPllReset.set(0)
            time.sleep(0.0001)
            dumpTiming(tim)
            tim.C_RxReset()
            time.sleep(1.0)
            tim.ClearRxCounters()

            rxId = xma.RxId.get()
            if (rxId==0 or rxId==0xffffffff or (rxId&0xff)>15):
                logging.critical(f"XPM Remote link id register illegal value: 0x{rxId:08x}. Aborting.  Try TxPllReset.");
                raise RuntimeError(f"Illegal XPM Remote link id. Try TxPllReset.")
    barrier_global.wait()
    rxId = xma.RxId.get()
    logging.info('rxId {:x}'.format(rxId))

    connect_info = {}
    connect_info['paddr'] = rxId

    return connect_info

# called on dealloc
def xpmdet_connectionShutdown():
    """Shut down the module barrier and return True."""
    barrier_global.shutdown()
    return True

#  Apply the full configuration
def xpmdet_connect(grp,length):
    """Configure each lane in the lane mask: set up its trigger event buffer for readout group `grp` and enable its TDetSemi channel with `length`; return True.

    The buffer index is the lane (or lane + 4 if ``args['core']`` is False); it gets PauseThreshold 16,
    Partition `grp`, TriggerSource 0, TriggerDelay 0 and MasterEnable True.
    """
    root = args['root']

    lm = args["lanemask"]
    for i in range(4):
        if (lm & (1<<i)):
            il = i if args['core'] else i+4
            teb = getattr(root.TDetTiming.TriggerEventManager,f'TriggerEventBuffer[{il}]')
            teb.ResetCounters()
            teb.PauseThreshold.set(16)
            teb.Partition.set(grp)
            teb.TriggerSource.set(0)
            teb.TriggerDelay.set(0)
            teb.MasterEnable.set(True)

            getattr(root.TDetSemi,f'Clear_{i}').set(1)
            getattr(root.TDetSemi,f'Length_{i}').set(length)
            getattr(root.TDetSemi,f'Clear_{i}').set(0)
            getattr(root.TDetSemi,f'Enable_{i}').set(1)

    return True

def xpmdet_unconfig():
    """For each lane in the lane mask, set TDetSemi 'Enable_<i>' to 0 and 'Clear_<i>' to 1; return ``args['root']``."""
    root = args['root']

    #  Clear TDetSemi
    lm = args["lanemask"]
    for i in range(4):
        if (lm & (1<<i)):
            getattr(root.TDetSemi,f'Enable_{i}').set(0)
            getattr(root.TDetSemi,f'Clear_{i}').set(1)

    return root
