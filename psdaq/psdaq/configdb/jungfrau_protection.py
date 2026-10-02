"""Command-line tool to set 'user.hot_pixel_threshold' and 'user.max_hot_pixels' of all jungfrau segments in the production config database."""
import argparse
import sys
from typing import List

from psdaq.configdb.configdb_multimod import configdb_multimod


def change_protection_settings():
    """Parse --adu and --max_pix (required) and call `configdb_multimod` twice with ``MODIFY=True`` to write them to '<detname>_<seg>' for seg 0..nsegs-1.

    Defaults: --cfg 'BEAM', --detname 'jungfrau', --hutch 'mfx', --nsegs 32.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(prog="jungfrau_gain_mode")
    parser.add_argument(
        "--adu",
        help="ADU in low gain threshold to consider pixel hot.",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--cfg", type=str, default="BEAM", help="Config alias, e.g. BEAM, TEST, etc."
    )
    parser.add_argument(
        "--detname", type=str, default="jungfrau", help="Base detector name."
    )
    parser.add_argument("--hutch", type=str, default="mfx", help="Hutch/instrument.")
    parser.add_argument(
        "--max_pix",
        help="Max number of pixels over threshold before activating detector protection.",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--nsegs",
        type=int,
        default=32,
        help="Number of jungfrau segments (all will be modified).",
    )
    args: argparse.Namespace = parser.parse_args()

    detector_segments: List[str] = []
    for seg in range(args.nsegs):
        detector_segments.append(f"{args.detname}_{seg}")

    configdb_multimod(
        URI_CONFIGDB="https://pswww.slac.stanford.edu/ws-auth/configdb/ws",
        DEV=args.cfg,
        INSTRUMENT=args.hutch,
        DETECTOR=detector_segments,
        CONFIG_KEY=["user","hot_pixel_threshold"],
        CONFIG_VALUE=args.adu,
        MODIFY=True,
    )
    configdb_multimod(
        URI_CONFIGDB="https://pswww.slac.stanford.edu/ws-auth/configdb/ws",
        DEV=args.cfg,
        INSTRUMENT=args.hutch,
        DETECTOR=detector_segments,
        CONFIG_KEY=["user","max_hot_pixels"],
        CONFIG_VALUE=args.max_pix,
        MODIFY=True,
    )


if __name__ == "__main__":
    change_protection_settings()
