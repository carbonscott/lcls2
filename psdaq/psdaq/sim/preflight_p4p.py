"""preflight_p4p.py get|timeout <PV>: preflight.sh's p4p (pvxs) client probe, the client control.py uses.

  get      the loopback positive control (step 4): a value within GET_TIMEOUT -> exit 0, none -> exit 3
  timeout  the isolation probe (step 2b): no value within GET_TIMEOUT -> exit 0, a value -> exit 1 (a leak)
  any other error in the probe -> exit 2 ('p4p probe broke: ...'); an error while importing, or while closing the
  client, exits 1 with a traceback. preflight.sh reads every nonzero exit as a leak in 'timeout' mode and as a failed
  positive control in 'get' mode.

GET_TIMEOUT bounds the network part: search, connect and get. Nothing else is bounded here: starting the interpreter
and importing p4p read the DAQ's conda env from a shared filesystem and their time varies with it (see "Time bounds"
in preflight.sh). Only preflight.sh's budget stops a stalled probe, and only a probe still running when the budget
runs out is HUNG (exit 4, no verdict; exit 1 if a leak was already seen). A stall that ends sooner is read as usual.
GET_TIMEOUT is wall-clock time: a stall during the get's wait uses up that much of it, and a probe frozen past the
get's deadline reads as no answer even if a server would have answered: exit 0 in 'timeout' mode, which preflight.sh
counts toward PASS, and exit 3 in 'get' mode. The first line says how long the imports took and the timeout line how
long making the client and the get took, so a stalled probe shows in the log; nothing acts on that.

The client context comes from pvwait.context (flake register F12: it retries only PVXS's IPv6 bind race), taken
from the pvwait.py next to this file, so the probe never depends on which psdaq build is on the path.
"""
import time
t0 = time.monotonic()
import os
import sys
from p4p.client.thread import TimeoutError
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from pvwait import context  # noqa: E402

GET_TIMEOUT = 5.0


def main(mode, pv):
    print('p4p probe: imports done in %.1f s' % (time.monotonic() - t0), flush=True)
    t1 = time.monotonic()
    try:
        c = context(who='preflight p4p' if mode == 'timeout' else 'preflight local p4p')
    except Exception as e:  # no client, no probe: a broken probe, never "no answer" (TimeoutError included)
        print('p4p probe broke: %s %s' % (type(e).__name__, e), flush=True)
        return 2
    rc = 2
    try:
        v = c.get(pv, timeout=GET_TIMEOUT)
        if mode == 'get':
            print('p4p local get: %s in %.2f s' % (float(v), time.monotonic() - t1), flush=True)
            rc = 0
        else:
            print('REACHED %s %s' % (pv, v), flush=True)
            rc = 1
    except TimeoutError as e:
        print('p4p timeout after %.1f s (GET_TIMEOUT %.0f s): %s' % (time.monotonic() - t1, GET_TIMEOUT, e), flush=True)
        rc = 3 if mode == 'get' else 0
    except Exception as e:
        print('p4p probe broke: %s %s' % (type(e).__name__, e), flush=True)
        rc = 2
    finally:
        c.close()
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
