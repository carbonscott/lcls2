"""Pedestal scan of '<detname>:user.gain_mode' over values 0-4 using `ConfigScanBase`."""
from psdaq.cas.config_scan_base import ConfigScanBase
import json

def main():

    # default command line arguments
    """Run the scan with defaults hutch 'rix', detname 'epixhr_0', 1000 events per step, record 1 and run_type 'DARK'.

    Each step sets ``<detname>:user.gain_mode`` to the gain value and uses it as the step
    value, with metadata {'detname', 'scantype': 'pedestal', 'step'}.
    """
    defargs = {'--hutch'   :'rix',
               '--detname' :'epixhr_0',
               '--scantype':'pedestal',
               '--events'  :1000,
               '--record'  :1,
               '--run_type':'DARK'}

    scan = ConfigScanBase(defargs=defargs)
    args = scan.args

    args.scantype = 'pedestal'
    keys = [f'{args.detname}:user.gain_mode']

    def steps():
        d = {}
        metad = {'detname':args.detname,
                 'scantype':args.scantype}
        for gain in range(5):
            d[f'{args.detname}:user.gain_mode'] = int(gain)
            metad['step'] = int(gain)
            yield (d, float(gain), json.dumps(metad))

    scan.run(keys,steps)

if __name__ == '__main__':
    main()
