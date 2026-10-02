"""Timing scan of '<detname>:user.start_ns' over 13 values from 700000 to 830000 using `ConfigScanBase`."""
from psdaq.cas.config_scan_base import ConfigScanBase
import json
import numpy as np

def main():

    # default command line arguments
    """Run the scan with defaults 1000 events per step, hutch 'mfx', detname 'epix100_0', record 0 and config 'BEAM'.

    Step i writes ``int(np.linspace(700000, 830000, 13)[i])`` to the key and uses i as the
    step value; metadata include 'step' and 'start_ns'.
    """
    defaults = {
        "--events": 1000,
        "--hutch": "mfx",
        "--detname": "epix100_0",
        "--scantype": "timing",
        "--record": 0,#1,
        "--config": "BEAM",
    }

    scan = ConfigScanBase(defargs=defaults)
    args = scan.args

    keys = []
    keys.append(f'{args.detname}:user.start_ns')

    def steps():
        d = {}
        metad = {}
        metad['detname'] = args.detname
        metad['scantype'] = 'timing'
        timing_vals = np.linspace(700000,830000,13)
        for delay_idx in range(13):
            #  Set the detector level config change
            d[f'{args.detname}:user.start_ns'] = int(timing_vals[delay_idx])
            #  Set the global meta data
            metad['step'] = delay_idx
            metad['start_ns'] = int(timing_vals[delay_idx])
            yield (d, float(delay_idx), json.dumps(metad))

    scan.run(keys, steps)

if __name__ == '__main__':
    main()
