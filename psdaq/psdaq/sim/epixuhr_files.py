"""epixuhr_files: the PLL tables and pixel bit maps an ePixUHR config store reads, for a simulated run.

epixuhr3x2_config_store.beam_cdict() and epixUHR_config_store.epixUHR_cdict() build their default
config from files in one directory (EPIXUHR_CONFIG_DIR, by default a facility path):

  pll/<name>.csv                 Si5345 register tables: a header line, then 'address,value' rows
                                 in hex (np.loadtxt(..., delimiter=',', skiprows=1, converters=hex))
  pixelBitMaps_prod/<name>.csv   one pixel configuration map per ASIC, 168 x 192 values

This writes files of those names and shapes with simulated content: each PLL table is a few
register writes (page select, then registers of that page); each pixel map is all zeros (every
pixel in the ASIC's default configuration).  Point EPIXUHR_CONFIG_DIR at the directory to build the
config with no facility filesystem.

    python -m psdaq.sim.epixuhr_files <dir>
"""

import argparse
import os
import sys

PLL_TABLES = ('PLLConfig_Si5345_temp_250', 'Si5345-B-156MHZ-out2-3-7-Registers',
              'Si5345-B-156MHZ-out-0-5-and-7-Registers', 'Si5345-B-156MHZ-out2-3-9',
              'Si5345-B-156MHZ-out-0-5-and-7-v2-Registers')
PIXEL_MAPS = ('0_default', '1_injection_truck', '2_injection_corners_FHG',
              '3_injection_corners_AHGLG1', '4_extra_config', '5_extra_config', '6_truck2',
              '7_on_the_fly')
ROWS, COLS = 168, 192


def write(d):
    """Write the files under directory d; returns the paths written."""
    out = []
    os.makedirs(os.path.join(d, 'pll'), exist_ok=True)
    os.makedirs(os.path.join(d, 'pixelBitMaps_prod'), exist_ok=True)
    for i, name in enumerate(PLL_TABLES):
        path = os.path.join(d, 'pll', name + '.csv')
        with open(path, 'w') as f:
            f.write('Address,Data\n')
            f.write('0x0001,0x%02X\n' % (i + 1))                        # page select
            for r in range(8):
                f.write('0x%04X,0x%02X\n' % (((i + 1) << 8) | (0x10 + r), (17 * r + i) & 0xff))
        out.append(path)
    row = ','.join(['0'] * COLS) + '\n'
    for name in PIXEL_MAPS:
        path = os.path.join(d, 'pixelBitMaps_prod', name + '.csv')
        with open(path, 'w') as f:
            f.write(row * ROWS)
        out.append(path)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('dir')
    a = ap.parse_args(argv)
    paths = write(a.dir)
    print('epixuhr_files: %d files under %s (EPIXUHR_CONFIG_DIR)' % (len(paths), a.dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
