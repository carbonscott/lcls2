#!/usr/bin/env python
"""Command module that prints which authentication ``MDBWebUtils`` will use for the calibration DB web service."""
import sys
import psana.pscalib.calib.MDBWebUtils as wu

def do_main():
    """Print ``MDBWebUtils.info_ticket`` and exit with status 0.

    ``info_ticket`` is set when ``MDBWebUtils`` is imported: the first 20 characters of the
    ``CALIB_JWT`` token if one is available, otherwise a note on Kerberos use or on missing tickets.
    """
    print(wu.info_ticket)
    sys.exit(0)

if __name__ == "__main__":
    do_main()

#EOF
