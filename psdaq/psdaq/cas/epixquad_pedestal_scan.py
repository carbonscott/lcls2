"""Pedestal scan of '<detname>:user.gain_mode' over values 0-4 using `ConfigScanBase`."""
from psdaq.cas.config_scan_base import ConfigScanBase
import json

def main():

    # default command line arguments
    """Run the scan with defaults 1000 events per step, hutch 'ued', detname 'epixquad_0', record 1 and run_type 'DARK'.

    Each step sets ``<detname>:user.gain_mode`` to the gain value and uses it as the step
    value, with metadata {'detname', 'scantype': 'pedestal', 'step'}.
    """
    defargs = {'--events'  :1000,
               '--hutch'   :'ued',
               '--detname' :'epixquad_0',
               '--scantype':'pedestal',
               '--record'  :1,
               '--run_type':'DARK'}

    scan = ConfigScanBase(defargs=defargs)
    args = scan.args

    keys = []
    keys.append(f'{args.detname}:user.gain_mode')

    def steps():
        d = {}
        metad = {}
        metad['detname'] = args.detname
        metad['scantype'] = 'pedestal'
        for gain in range(5):
            #  Set the detector level config change
            d[f'{args.detname}:user.gain_mode'] = gain
            #  Set the global meta data
            metad['step'] = gain
            yield (d, float(gain), json.dumps(metad))

    scan.run(keys, steps)

if __name__ == '__main__':
    main()

