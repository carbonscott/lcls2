"""simdetprot: a software detector-protection (blocker) IOC over Channel Access, so detector_protection_monitor runs
with no protection IOC.

It serves the four PVs trigger/detector_protection_monitor.py reads under a base PV: <base>:BLOCKED (a new timestamp
on it is a protection activation), <base>:NPIX (the hot-pixel count that trips), <base>:NPIX_OT (the hot-pixel count
now), <base>:ADU (the ADU threshold of a hot pixel); once a second NPIX_OT steps through 0 .. NPIX - 1 (never over the
threshold by itself).  Simulator-only PVs: <base>:SIM:TRIP (a put of any value writes BLOCKED = 1 with a new
timestamp: the protection trips), <base>:SIM:PID (this process's pid: a client can tell the simulator from an IOC).
--trip-after S also trips once, S seconds after start.

Channel Access stays on this host: the server (caproto) serves only the interfaces of EPICS_CAS_INTF_ADDR_LIST, which
must be loopback (psdaq/psdaq/sim/sim_env.sh sets it, with EPICS_CAS_BEACON_ADDR_LIST=127.0.0.1, auto beacons off and
the non-default ports EPICS_CA_SERVER_PORT / EPICS_CAS_SERVER_PORT), unless --allow-remote.

    python -m psdaq.sim.simdetprot -P DAQ:SIM:JF16M:BLOCKER [--npix 100] [--adu 2000] [--trip-after 4]
"""

import argparse
import ipaddress
import os
import sys
import time


def require_loopback_cas_env(environ):
    """The CA server env: interfaces and beacons only loopback, auto beacons off."""
    bad = []
    intf = (environ.get('EPICS_CAS_INTF_ADDR_LIST') or '').split()
    if not intf:
        bad.append('EPICS_CAS_INTF_ADDR_LIST is empty (caproto would serve every interface)')
    for key in ('EPICS_CAS_INTF_ADDR_LIST', 'EPICS_CAS_BEACON_ADDR_LIST'):
        for e in (environ.get(key) or '').split():
            h = e.split(':', 1)[0]
            try:
                if not ipaddress.ip_address(h).is_loopback:
                    bad.append('%s entry %s is not loopback' % (key, e))
            except ValueError:
                bad.append('%s entry %s is not an IP literal' % (key, e))
    if (environ.get('EPICS_CAS_AUTO_BEACON_ADDR_LIST') or '').upper() != 'NO':
        bad.append('EPICS_CAS_AUTO_BEACON_ADDR_LIST is not NO')
    return bad


def make_ioc(prefix, npix, adu, trip_after):
    from caproto.server import PVGroup, pvproperty

    class DetProt(PVGroup):
        BLOCKED = pvproperty(value=0, name=':BLOCKED', doc='a new timestamp: protection activated')
        NPIX = pvproperty(value=npix, name=':NPIX', doc='hot-pixel count that trips')
        NPIX_OT = pvproperty(value=0, name=':NPIX_OT', doc='hot pixels now')
        ADU = pvproperty(value=adu, name=':ADU', doc='ADU threshold of a hot pixel')
        TRIP = pvproperty(value=0, name=':SIM:TRIP', doc='simdetprot only: a put trips the protection')
        PID = pvproperty(value=os.getpid(), name=':SIM:PID', read_only=True, doc='simdetprot only: its pid')

        @NPIX_OT.scan(period=1.0)
        async def NPIX_OT(self, instance, async_lib):
            self.n = getattr(self, 'n', 0) + 1
            if trip_after is not None and not getattr(self, 'tripped', False) and self.n >= trip_after:
                self.tripped = True
                await self.BLOCKED.write(1, timestamp=time.time())
            await instance.write((self.n * 7) % max(1, self.NPIX.value))

        @TRIP.putter
        async def TRIP(self, instance, value):
            await self.BLOCKED.write(1, timestamp=time.time())
            return value

    return DetProt(prefix=prefix)


def main():
    ap = argparse.ArgumentParser(description='software detector-protection IOC (CA) for detector_protection_monitor')
    ap.add_argument('-P', required=True, metavar='BASE', help='base PV, as detector_protection_monitor -b')
    ap.add_argument('--npix', type=int, default=100, help='NPIX, the hot-pixel count that trips (default %(default)s)')
    ap.add_argument('--adu', type=int, default=2000, help='ADU threshold (default %(default)s)')
    ap.add_argument('--trip-after', type=float, default=None, help='trip once, this many seconds after start')
    ap.add_argument('--allow-remote', action='store_true', help='allow a non-loopback CA server env')
    a = ap.parse_args()
    bad = require_loopback_cas_env(os.environ)
    if bad and not a.allow_remote:
        raise SystemExit('simdetprot: refusing a CA server env that is not loopback-only: %s (source sim_env.sh)'
                         % '; '.join(bad))
    if os.environ.get('EPICS_CA_REPEATER_PORT') and not os.environ.get('EPICS_CAS_BEACON_PORT'):
        os.environ['EPICS_CAS_BEACON_PORT'] = os.environ['EPICS_CA_REPEATER_PORT']   # beacons to sim_env's port
    from caproto.server import run
    ioc = make_ioc(a.P, a.npix, a.adu, a.trip_after)
    intf = (os.environ.get('EPICS_CAS_INTF_ADDR_LIST') or '127.0.0.1').split()
    print('simdetprot: ready, %d PVs under %s on %s port %s, pid %d' % (
        len(ioc.pvdb), a.P, ' '.join(intf), os.environ.get('EPICS_CAS_SERVER_PORT') or
        os.environ.get('EPICS_CA_SERVER_PORT'), os.getpid()), flush=True)
    run(ioc.pvdb, interfaces=intf, log_pv_names=False)


if __name__ == '__main__':
    sys.exit(main())
