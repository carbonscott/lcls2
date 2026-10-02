"""Prometheus exporter that monitors XPM and timing-receiver PVs and records problems as gauge metrics.

PV monitors (via `psdaq.cas.pvedit`) feed a `CustomCollector`, which is served over
HTTP by `prometheus_client`; `main` sets up the checks and polls timing updates.
"""
import argparse
import datetime
import logging
import time
import datetime
import copy
from psdaq.cas.pvedit import *
from psdaq.cas.xpm_utils import xpmLinkId

from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, SummaryMetricFamily, REGISTRY

PROM_PORT_BASE = 9200
MAX_PROM_PORTS = 100

RX_POWER_MIN = 0.02

d = {'checkTiming':{},   # [pvname] = (cb,state)
     'monitor':[],       # callbacks
     'dslinks':{},       # [xpmid][linkid] = cb
}

class CustomCollector():
    """Prometheus collector holding gauge values as {family: {name: value}}."""
    def __init__(self):
        self._d = {}

    def register(self, family, name, value, overwrite):
        """Store `value` for (`family`, `name`) if new or if `overwrite`.

        Returns
        -------
        bool
            True if the value was stored, False otherwise.
        """
        d = self._d
        if family not in d.keys():
            d[family] = {}
        if name not in d[family].keys() or overwrite:
            d[family][name] = value
            return True
        return False


    def collect(self):
#        d = copy.deepcopy(self._d)
#        self._d = {}
        """Yield one `GaugeMetricFamily` per family, with label 'id' set to each stored name."""
        d = self._d
        for family, entry in d.items():
#            logging.warning(f'collect {family} {len(entry)}')
            g = GaugeMetricFamily(family,documentation='',labels=['id'])
            for name,value in entry.items():
                g.add_metric([name],value)
            yield g

        if False:
            d = self._summ
            for family, entry in d.items():
#                logging.warning(f'collect {family} {len(entry)}')
                g = SummaryMetricFamily(family,documentation='',labels=['id'])
                for name,value in entry.items():
                    g.add_metric([name],value[0],value[1])
                yield g

c = CustomCollector()

class CustomCb(object):
    
    """Base callback that tracks an occurrence count and last severity in the collector.

    For a non-None `family` (':' replaced by '_', lower-cased), the gauges
    '<family>_occurrences' and '<family>_severity' for `name` are registered as 0.
    """
    def __init__(self, family, name):
        if family is not None:
            self._family = family.replace(':','_').lower() # generally derived from PV name
            self._name = name
            self._occ = 0
            self._sev = 0
            c.register(self._family+'_occurrences', self._name, self._occ, True)
            c.register(self._family+'_severity'   , self._name, self._sev, True)

    def record(self, value):
        """Increment the occurrence count, set the severity to `value` and update both gauges."""
        self._occ += 1
        self._sev = value
        c.register(self._family+'_occurrences', self._name, self._occ, True)
        c.register(self._family+'_severity'   , self._name, self._sev, True)

class EmptyCb(CustomCb):

    """Callback that only remembers the latest value of PV `pv` in `last`."""
    def __init__(self,family,name,pv,isStruct=False):
        super().__init__(family,name)
        self.pv = None
        self.last = None
        initPvMon(self,pv,isStruct)

    def update(self,err=None):
        """Store the cached PV value in `last`."""
        self.last = self.pv.__value__

class RangeCb(CustomCb):

    """Callback that records the PV value when it is outside [`lo`, `hi`]."""
    def __init__(self, family, name, pv, lo, hi):
        super().__init__(family, name)
        self.pv = None
        self.lo = lo
        self.hi = hi
        initPvMon(self,pv)

    def update(self,err=None):
        """Log the value; if it is below `lo` or above `hi`, log an error and `record` the value."""
        logging.info(f'RangeCb {self.pv.pvname}  {self.pv.__value__}')
        if self.pv.__value__ < self.lo or self.pv.__value__ > self.hi:
            logging.error(f'{self.pv.pvname} = {self.pv.__value__} is out of range [{self.lo},{self.hi}]')
            self.record(self.pv.__value__)

class LatchCb(CustomCb):

    """Callback for a latch PV; when it reads 1 it is counted and cleared by writing 1 to PV `clear`."""
    def __init__(self, family, name, pv,clear):
        super().__init__(family, name)
        self.pv = None
        self.clear = Pv(clear)
        initPvMon(self,pv)

    def update(self,err=None):
        """If the PV value is 1, record severity+1, log an error and put 1 to the clear PV."""
        if self.pv.__value__ == 1:
            self.record(self._sev+1) # integrating
            logging.error(f'{self.pv.pvname} latched.  Clearing...')
            self.clear.put(1)

class TimeCb(CustomCb):

    """Callback comparing a PV holding seconds since 1990-01-01 with the current UTC time.

    The constructor is declared ``__init__(family, name, pv)`` without `self`, so
    creating an instance raises TypeError.
    """
    def __init__(family,name,pv):
        super().__init__(family,name)
        self.pv = None
        initPvMon(self,pv)

    def update(self,err=None):
        """If the PV time differs from now by more than 5 s, log a warning, record the difference and set gauge 'xpm_timedelta_seconds'."""
        logging.info(f'TimeCb {self.pv.pvname}  {self.pv.__value__}')
        pvsec = self.pv.__value__
        dtsec = (datetime.datetime.utcnow()-datetime.datetime(1990,1,1)).total_seconds()
        diff = pvsec - dtsec
        if diff < -5 or diff > 5:
            logging.warning(f'{self.pv.pvname} is off by {diff} seconds')
            self.record(diff)
            c.register('xpm_timedelta_seconds',self.pv.pvname, diff,True)

class DsLinkCb(CustomCb):

    """Callback for '<pv>:LinkRxErr<link>', also tracking '<pv>:LinkRxRcv<link>' and an optional remote ID."""
    def __init__(self, family, pv, link):
        super().__init__(family,f'{pv}:LinkRxErr{link}')
        self.pv = None
        self.remoteId = None
        self.rxrcv = EmptyCb(None,None,f'{pv}:LinkRxRcv{link}')
        initPvMon(self,f'{pv}:LinkRxErr{link}')

    def link(self, remoteId):
        """Store `remoteId` and log the link with its `xpmLinkId` names."""
        logging.warning(f'Link {xpmLinkId(remoteId)} to {self.pv.pvname}')
        self.remoteId = remoteId

    def unlink(self):
        """Clear the stored remote ID."""
        self.remoteId = None

    def update(self,err=None):
        """Record the rx-error value (added to the severity) when it is > 0 and the link has receive counts or a remote ID; log warnings/errors."""
        rxrcv = self.rxrcv.last
        v = self.pv.__value__
        if rxrcv is not None:
            hasRemote = rxrcv > 0 or self.remoteId is not None
            if (v > 0 and hasRemote): # or self._record:
                self.record(self._sev+v)
#                logging.warning(f'DsLinkCb {self.pv.pvname}[{self.remoteId}]  {v} {rxrcv}')

        if self.pv.__value__>0 and rxrcv is not None:
            if rxrcv>0:
                logging.warning(f'{self.pv.pvname} = {self.pv.__value__}, rxrcv = {rxrcv}')
            if self.remoteId is not None and self.pv.__value__>0:
                logging.error(f'{self.pv.pvname} {xpmLinkId(self.remoteId)}: rxerr {self.pv.__value__}  rxrcv {rxrcv}')

class RemoteLinkCb(CustomCb):

    """Callback checking a receiver's remote-link ID PV and linking it to the matching `DsLinkCb`.

    `pvbase` is a tuple (rx ID PV, tx ID PV name or int, name).
    """
    def __init__(self,pvbase):
        super().__init__('tim_remlink_id',pvbase[2])
        rxid = pvbase[0]
        txid = pvbase[1]
        self.pv = None
        if isinstance(txid,int):
            self.txid = txid
        else:
            self.txpv = Pv(txid, self.update)
            self.txid = txid
        self.last = None
        initPvMon(self,rxid)

    def _txid(self):
        if isinstance(self.txid,int):
            return self.txid
        else:
            return self.txpv.__value__

    def update(self,err=None):
        """Validate the rx ID and update which XPM downstream link this receiver is attached to.

        Returns early if either ID is None. An ID that is 0, -1 or whose top byte is not
        0xff records severity 1. Otherwise, if the ID changed, the old link is unlinked and
        the new one linked; an unknown XPM records severity 2.
        """
        logging.info(f'RemoteLinkCb {self.pv.pvname}  {self.pv.__value__}')
        rxid = self.pv.__value__
        txid = self._txid()
        if rxid is None or txid is None:
            return
        if rxid == 0 or rxid == -1 or (rxid>>24) != 0xff:
            self.record(1)
            logging.error(f'{self.pv.pvname} = {rxid}')
        else:
            if rxid == self.last:
                return  # nothing to do
            if self.last is not None:
                xpmid  = self.last&0x00ffff00
                linkid = (self.last>> 0)&0xf
                d['dslinks'][xpmid][linkid].unlink()
            xpmid  = rxid&0x00ffff00
            linkid = (rxid>> 0)&0xf
            if xpmid in d['dslinks'].keys():
                d['dslinks'][xpmid][linkid].link(self._txid())
                self.last = rxid
            else:
                self.record(2)
                logging.error(f'xpm not found for {self.pv.pvname} {rxid:x}')
                self.last = None

class SFPCb(object):

    """Callback for a structured SFP status PV."""
    def __init__(self, pv):
        self.pv = None
        initPvMon(self,pv,isStruct=True)

    def update(self,err=None):
        """For each of 14 modules that is present, log at info level if LossOfSignal is 1 or RxPower is below `RX_POWER_MIN` (0.02)."""
        v = self.pv.__value__
        modabs = v.value.ModuleAbsent
        los    = v.value.LossOfSignal
        rxp    = v.value.RxPower
        for i in range(14):
            if modabs[i]==0:
                if los[i]==1:
                    logging.info(f'{self.pv.pvname}: AMC{i//7}-{i%7} has ~MODABS with LOS')
                elif rxp[i] < RX_POWER_MIN:
                    logging.info(f'{self.pv.pvname}: AMC{i//7}-{i%7} RxPwr = {rxp[i]}')

#
#  Monitor and report link state changes and update frequency changes
#          
def checkTiming(family,name,pv):
    """Monitor structured PV `pv` with an `EmptyCb` and register it in ``d['checkTiming']`` with state 1."""
    logging.info(f'checkTiming({pv})')
    c = EmptyCb(family,name,pv,True)
    d['checkTiming'][pv] = (c,1)

def checkTiming_update(now):
    """For each monitored timing PV, record 1 when its timestamp is more than 5 s older than `now` and record 0 when it resumes.

    `now` is seconds since 1990-01-01. The log messages lack the f-prefix, so '{pv}' is printed literally.
    """
    logging.info(f'checkTiming_update({now})')
    for pv,t in d['checkTiming'].items():
        v = t[0].pv.__value__
        if now - v.timeStamp.secondsPastEpoch > 5:
           if t[1]==1:
               t[0].record(1)
               logging.error('{pv} stopped')
               d['checkTiming'][pv] = (t[0],0)
        elif t[1]==0:
            t[0].record(0)
            logging.error('{pv} resumed')
            d['checkTiming'][pv] = (t[0],1)

def checkRange(pvbase,pvext,vlo,vhi):
    """Add a `RangeCb` for '<pvbase>:<pvext>' with limits `vlo`, `vhi` to ``d['monitor']``."""
    pv = pvbase+':'+pvext
    logging.info(f'checkRange {pv}: {vlo}-{vhi}')
    d['monitor'].append(RangeCb(pvext, pvbase, pv, vlo, vhi))

def checkLatch(pvbase,pvext,clear):
    """Add a `LatchCb` for '<pvbase>:<pvext>' that clears via PV `clear` to ``d['monitor']``."""
    latch = pvbase+':'+pvext
    logging.info(f'checkLatch({latch})')
    d['monitor'].append(LatchCb(pvext, pvbase, latch, clear))
        
def checkTime(pvbase,pvext):
    """Add a `TimeCb` for '<pvbase>:<pvext>' to ``d['monitor']`` (construction raises TypeError; see `TimeCb`)."""
    pv = pvbase+':'+pvext
    logging.info(f'checkTime({pv})')
    d['monitor'].append(TimeCb(pvext,pvbase,pv))

def checkDsLinks(ip, pvbase, nLinks):
    """Create `nLinks` `DsLinkCb` monitors for XPM `pvbase` under an XPM ID derived from the PV name and IP.

    The ID is ``int(last PV field) << 16``, plus bits from the IP when it starts with '10.'.
    """
    logging.info(f'checkDsLinks({pvbase},{nLinks})')
    xpmid = (int(pvbase.split(':')[-1])<<16)
    ipw = ip.split('.')
    if ipw[0]=='10':
        xpmid |= (int(ipw[2])<<12) | ((int(ipw[3])-100)<<8)

    d['dslinks'][xpmid] = {i : DsLinkCb('xpm_dslink_err',pvbase,i) for i in range(nLinks)}

def checkSFPs(pvbase):
    """Add an `SFPCb` for PV `pvbase` to ``d['monitor']``."""
    logging.info(f'checkSFPs({pvbase})')
    d['monitor'].append(SFPCb(pvbase))

def checkQSFPs(pvbase):
    """Log the call only; the QSFP check is commented out."""
    logging.info(f'checkQSFPs({pvbase})')
# No indication of when something is connected
#    d['monitor'].append(QSFPCb(pvbase))

def checkXPM(arg):
    """Set up the monitors for one XPM given as (ip, pvbase), depending on its '<pvbase>:FwBuild' string.

    Without 'Gen' in the build string, timing checks are added (Cu/XTPG checks if 'xtpg'
    is present, else Us checks); then 8 downstream links plus QSFPs ('Kcu' builds) or 14
    links plus SFPs. If reading FwBuild fails the error is logged and `v` stays unset (NameError).
    """
    logging.info(f'checkXPM({arg})')

    ip     = arg[0]
    pvbase = arg[1]
    try:
        fw = Pv(pvbase+':FwBuild')
        v = fw.get()
    except:
        logging.error(f'Failed to read {pvbase}:FwBuild')

    # check if the firmware version is up-to-date

    # check the timing input
    if 'Gen' not in v:
        if 'xtpg' in v:
            checkTiming('tim_stopped',pvbase,pvbase+':Cu:RxLinkUp')
            checkRange(pvbase,'Cu:FIDs',354,366)
            checkLatch(pvbase,'XTPG:FiducialErr',
                       pvbase+':XTPG:ClearErr')
            checkTime(pvbase,'XTPG:TimeStamp')
        else:
            checkTiming('tim_stopped',pvbase,pvbase+':Us:RxLinkUp')
            checkRange(pvbase,'Us:FIDs',919.e3,938.e3)
    # check the AMCs,SFPs
    if 'Kcu' in v:
        checkDsLinks(ip,pvbase,8)
        checkQSFPs  (pvbase+':QSFPSTATUS')
    else:
        checkDsLinks(ip,pvbase,14)
        checkSFPs   (pvbase+':SFPSTATUS')

def checkTDET(pvbase):
    """Add a `RemoteLinkCb` for the (rx PV, tx PV or ID, name) tuple `pvbase` to ``d['monitor']``."""
    logging.info(f'checkTDET({pvbase}')
    d['monitor'].append(RemoteLinkCb(pvbase))

def createExposer(prometheusDir):
    """Start the Prometheus HTTP server on the first free port from 9200 and write '<dir>/drpmon_<host>_<i>.yaml'.

    Returns
    -------
    bool or None
        True on success; False if writing the file fails or no port 9200-9299 is free;
        None (after a warning) if `prometheusDir` is ''.
    """
    if prometheusDir == '':
        logging.warning('Unable to update Prometheus configuration: directory not provided')
        return

    hostname = socket.gethostname()
    for i in range(MAX_PROM_PORTS):
        port = PROM_PORT_BASE + i
        try:
            start_http_server(port)
            fileName = f'{prometheusDir}/drpmon_{hostname}_{i}.yaml'
            # Commented out the existing file check so that the file's date is refreshed
            if True: #not os.path.exists(fileName):
                try:
                    with open(fileName, 'wt') as f:
                        f.write(f'- targets:\n    - {hostname}:{port}\n')
                except Exception as ex:
                    logging.error(f'Error creating file {fileName}: {ex}')
                    return False
            else:
                pass            # File exists; no need to rewrite it
            logging.warning(f'Providing run-time monitoring data on port {port}')
            return True
        except OSError:
            pass                # Port in use
    logging.error('No available port found for providing run-time monitoring')
    return False

def main():

    #  Need IP addresses to distinguish NEH/FEH
    """Parse arguments, set up XPM and timing-receiver monitors, register the collector and poll timing every 4 s.

    Polling runs only while `createExposer` returns True.

    Notes
    -----
    As written the code calls ``tdets.extent`` (AttributeError), iterates ``args.xpm``
    (None unless --xpm is given) and builds 2-tuples for --drp entries that
    `RemoteLinkCb` indexes at [2].
    """
    xpms = {'NEH' : [('10.0.1.102','DAQ:NEH:XPM:0'),
                     ('10.0.2.102','DAQ:NEH:XPM:1'),
                     ('10.0.3.103','DAQ:NEH:XPM:2'),
                     ('10.0.2.103','DAQ:NEH:XPM:3'),
                     ('10.0.3.105','DAQ:NEH:XPM:4'),
                     ('10.0.1.104','DAQ:NEH:XPM:5'),
                     ('10.0.1.105','DAQ:NEH:XPM:6'),],
            'FEH' : [('10.0.1.107','DAQ:FEH:XPM:0'),
                     ('10.0.6.102','DAQ:FEH:XPM:1'),
                     ('10.0.7.102','DAQ:FEH:XPM:2'),
                     ('0,0,0,0'   ,'DAQ:FEH:XPM:3'),],
            'FEE' : [('10.0.5.102','DAQ:NEH:XPM:10'),
                     ('10.0.5.104','DAQ:NEH:XPM:11'),],
            'B84' : [('0.0.0.0'   ,'DAQ:LAB2:XPM:1'),
                     ('0.0.0.0'   ,'DAQ:LAB2:XPM:2'),],
    }

    drps = {'NEH' : [f'DRP:SRCF:CMP{i:03d}' for i in (1,3,28,11,13,26, #TMO
                                                      2,10,25,12,27,   #RIX
                                                  )],
            'FEH' : [f'DRP:SRCF:CMP{i:03d}' for i in (37, #TXI
                                                      14,31,44,33,35,38,39, #MFX
                                                  )],
            'FEE' : [f'DRP:NEH:CMP{i:03d}' for i in (1,5)],
            'B84' : [],
    }

    # FIMs/Wave8s
    fims = {'NEH' : ['MR2K4:FIM:W8:01', # :Top:TriggerEventManager:XpmMessageAligner', + ':RxId',':TxId'
                     'MR3K4:FIM:W8:01',
                     'LM1K4:W8:04',
                     'RIX:CRIX:W8:01',
                     'RIX:QRIX:W8:01',
                     'MR4K2:FIM:W8:02',
                     'MR3K2:FIM:W8:01',],
            'FEH' : [],
            'FEE' : [],
            'B84' : [],
    }

    hsds = {'NEH' : ['DAQ:TMO:HSD:1_1A', #':A:PADDR_U',
                     'DAQ:TMO:HSD:1_1B',
                     'DAQ:TMO:HSD:1_3E',
                     'DAQ:TMO:HSD:1_3D',
                     'DAQ:TMO:HSD:1_01',
                     'DAQ:TMO:HSD:1_DA',
                     'DAQ:TMO:HSD:1_B2',
                     'DAQ:TMO:HSD:1_B1',
                     'DAQ:TMO:HSD:1_89',
                     'DAQ:TMO:HSD:1_88',
#                     'DAQ:TMO:HSD:2_41',
                     'DAQ:RIX:HSD:1_1A',
                     'DAQ:RIX:HSD:1_1B',
                 ],
            'FEH' : [],
            'FEE' : [],
            'B84' : [],
    }

    hsdHosts = {'TMO':{'1': socket.gethostbyname('daq-tmo-hsd-01'),
                       '2': socket.gethostbyname('daq-tmo-hsd-02')},
                'RIX':{'1': socket.gethostbyname('daq-rix-hsd-01')}}
    def hsdId(base):
        bfields = base.split(':')
        hostIp  = hsdHosts[bfields[1]][bfields[3][0]]
        hfields = hostIp.split('.')
        return 0xfc000000 + int(hfields[3]) + (int(hfields[2])<<8) + (int(bfields[3][-2:],16)<<16)

    parser = argparse.ArgumentParser(description='simple pv monitor gui')

    parser.add_argument("pvs", help="pvs to monitor (NEH,FEH,FEE,B84)", nargs='+',default=['NEH','FEH'])
    parser.add_argument('-M', required=False, help='Prometheus config file directory', metavar='PROMETHEUS_DIR', default='')
    parser.add_argument("--xpm", help='XPM (IP,PV) entry', nargs='+', type=str)
    parser.add_argument("--drp", help='DRP (PV) entry', nargs='+', type=str)
    parser.add_argument("--fim", help='FIM (PV) entry', nargs='+', type=str)
    parser.add_argument("--hsd", help='HSD (PV) entry', nargs='+', type=str)
    parser.add_argument("-v", help='Verbosity', action='store_true')
    parser.add_argument("-vv", help='Verbosity', action='store_true')
    parser.add_argument("-vvv", help='Verbosity', action='store_true')
    args = parser.parse_args()

    if args.vvv:
        LEVEL=logging.DEBUG
    elif args.vv:
        LEVEL=logging.INFO
    elif args.v:
        LEVEL=logging.WARNING
    else:
        LEVEL=logging.ERROR

    FORMAT='%(asctime)s %(levelname)s %(message)s'
    logging.basicConfig(level=LEVEL, format=FORMAT)

    for s in args.pvs:
        if s in xpms.keys():
            for pv in xpms[s]:
                checkXPM(pv)
        else:
            print(f'XPMs for {s} not found')

    for s in args.xpm:
        a = s.split(',')
        if (len(a)!=2 or len(a[0].split('.'))!=4):
            raise ValueError(f'xpm entry [{s}] does not decode to IP,PV')
        checkXPM(a)

    tdets = []
    for s in args.pvs:
        #  Create the master list of timing link IDs from drps, fims, hsds
        tdets.extent([(f'{base}:RXID',f'{base}:TXID',base) for base in drps[s]])
        tdets.extend([(f'{base}:Top:TriggerEventManager:XpmMessageAligner:RxId',
                       f'{base}:Top:TriggerEventManager:XpmMessageAligner:TxId',
                       base) for base in fims[s]])
        tdets.extend([(f'{base}:A:PADDR_U',hsdId(base),base) for base in hsds[s]])

    tdets.extend([(f'{base}:RXID',f'{base}:TXID') for base in args.drp])
    tdets.extend([(f'{base}:Top:TriggerEventManager:XpmMessageAligner:RxId',
                   f'{base}:Top:TriggerEventManager:XpmMessageAligner:TxId',
                   base) for base in args.fim])
    tdets.extend([(f'{base}:A:PADDR_U',hsdId(base),base) for base in args.hsd])

    for pv in tdets:
        checkTDET(pv)

    epoch = datetime.datetime(1990,1,1)

    REGISTRY.register(c)
    time.sleep(4)

#    c.collect()

    rc = createExposer(args.M)
    while rc:
        now = (datetime.datetime.utcnow()-epoch).total_seconds()
        checkTiming_update(now)
        time.sleep(4)
        
if __name__ == '__main__':
    main()
