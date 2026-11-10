import rogue.hardware.pgp
import pyrogue
import pyrogue.utilities.prbs
import pyrogue.utilities.fileio
import pyrogue.protocols.epicsV4
import threading
import socket
import signal
import atexit
import yaml
import time
import sys
import argparse
import inspect
import wave8 as w8
#from AdmPcieKu3Pgp2b import *
import pyrogue.utilities.prbs

# Set the argument parser
parser = argparse.ArgumentParser()

# Add arguments
parser.add_argument(
    "--l", 
    type     = int,
    required = False,
    default  = 0,
    help     = "PGP lane number",
)

parser.add_argument(
    "--dev", 
    type     = str,
    required = False,
    default  = '/dev/datadev_0',
    help     = "PGP device (default /dev/datadev_0)",
)  

parser.add_argument(
    "--hvBay0En", 
    type     = bool,
    required = False,
    default  = False,
    help     = "Enable HV generator bay 0",
)

parser.add_argument(
    "--hvBay1En", 
    type     = bool,
    required = False,
    default  = False,
    help     = "Enable HV generator bay 1",
)

parser.add_argument(
    "--base", 
    type     = str,
    required = False,
    default  = 'DAQ:WAVE8',
    help     = "PVA Base",
)

# Get the arguments
args = parser.parse_args()

# A simulated device ('sim://...', psdaq/psdaq/sim): rogue's hardware transports become psdaq.sim.rogue_dev's, in process
if args.dev.startswith('sim://'):
    from psdaq.sim import rogue_dev
    rogue_dev.install(args.dev, det_type='wave8pvs')

# Since rogue 5 a Root takes pollEn, initRead and timeout when it is made, and its start() takes nothing;
# wave8 1.0.1's Top has no dataCapture (it always opens its data lanes)
rootArgs = dict(pollEn=False, initRead=True, timeout=5.0)
startArgs = len(inspect.signature(pyrogue.Root.start).parameters) > 1
topArgs = dict(hwType='datadev', dev=args.dev, lane=args.l, hvBay0En=args.hvBay0En, hvBay1En=args.hvBay1En)
if 'dataCapture' in inspect.signature(w8.Top.__init__).parameters:
    topArgs['dataCapture'] = False

# Set base
Wave8Board = w8.Top(**topArgs, **({} if startArgs else rootArgs))

# Add problematic registers to a special group
noPVA = [Wave8Board.AxiVersion.GitHash._groups]
for v in noPVA:
    if 'NoPVA' not in v:
        v.append('NoPVA')

# Set poll interval for important registers
pollRegs = ['TriggerEventManager.XpmMessageAligner.RxId',
            'TriggerEventManager.TriggerEventBuffer[0].XpmPause',
            'TriggerEventManager.TriggerEventBuffer[0].XpmOverflow',
            'TriggerEventManager.TriggerEventBuffer[0].FifoPause',
            'TriggerEventManager.TriggerEventBuffer[0].FifoOverflow',
            'TriggerEventManager.TriggerEventBuffer[0].PauseToTrig',
            'TriggerEventManager.TriggerEventBuffer[0].NotPauseToTrig',
            'RawBuffers.TrigCnt',
            'RawBuffers.FifoPauseCnt',
            'Integrators.IntFifoPauseCnt',
            'Integrators.ProcFifoPauseCnt',
]
for i in range(8):
    pollRegs.append('RawBuffers.OvflCntBuff[%d]'%i)

# handle [x] in attribute names
def setPollInterval(top,regname,value):
    path = regname.split('.')
    v = top
    for arg in path:
        v = getattr(v,arg)
    v.pollInterval = value

print(pollRegs)    
for v in pollRegs:
    setPollInterval(Wave8Board,v,1)

# Some registers cannot be controlled reliably when polling
noPollRegs = ['TriggerEventManager.TriggerEventBuffer[0].MasterEnable',
              'BatcherEventBuilder.Blowoff']
for v in noPollRegs:
    setPollInterval(Wave8Board,v,0)

epics = pyrogue.protocols.epicsV4.EpicsPvServer(base=args.base,root=Wave8Board,incGroups=None,excGroups=['NoPVA'])

def main():

    # Start the system
    if startArgs:
        Wave8Board.start(**rootArgs)
    else:
        Wave8Board.start()

    # Enable components for PVA
    Wave8Board.BatcherEventBuilder.enable.set(True)
    getattr(Wave8Board.TriggerEventManager,'TriggerEventBuffer[0]').enable.set(True)

    # Set the timing link txId
    ip = socket.inet_aton(socket.gethostbyname(socket.gethostname()))
    id = (0xfa<<24) | (ip[2]<<8) | (ip[3])
    Wave8Board.TriggerEventManager.XpmMessageAligner.TxId.set(id)

    # Start EPICS
    epics.start()
    epics.dump()

# Close window and stop polling
def stop():
    mNode.stop()
    Wave8Board.stop()
    exit()

if __name__ == '__main__':
    main()

    print('Main complete')
