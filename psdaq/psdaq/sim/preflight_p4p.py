"""preflight_p4p.py get|timeout <PV>: preflight.sh's p4p (pvxs) client probe, the client control.py uses.

  get      the loopback positive control (step 4): a value within GET_TIMEOUT -> exit 0, none -> exit 3
  timeout  the isolation probe (step 2b): no value within GET_TIMEOUT -> exit 0, a value -> exit 1 (a leak)
  any other error in the probe -> exit 2

GET_TIMEOUT bounds the network part: search, connect and get. Starting the interpreter and importing p4p are not
bounded here: they read the DAQ's conda env from a shared filesystem and their time varies with it (see "Time
bounds" in preflight.sh). The first line says how long the imports took, so a probe that preflight.sh's budget
stopped before it reached the network is told apart from one that reached it.
"""
import time
t0 = time.monotonic()
import signal
import sys
from p4p.client.thread import Context, TimeoutError

GET_TIMEOUT = 5.0
CONTEXT_TRIES = 3


def context():
    """Context('pva'), tried up to CONTEXT_TRIES times. pvxs 1.2 binds its IPv6 search socket to the port the kernel
    picked for the IPv4 one and does not retry (client.cpp: 'Unable to bind random UDP6 port'), so creating a client
    fails now and then when another socket holds that port for IPv6. Nothing is sent before the client exists, so
    another try changes nothing about what the probe tests; failing every try still fails the probe."""
    for n in range(1, CONTEXT_TRIES + 1):
        try:
            return Context('pva')
        except RuntimeError as e:
            print('p4p probe: creating the client failed (try %d of %d): %s' % (n, CONTEXT_TRIES, e), flush=True)
            if n == CONTEXT_TRIES:
                raise


def main(mode, pv):
    print('p4p probe: imports done in %.1f s' % (time.monotonic() - t0), flush=True)
    signal.alarm(int(GET_TIMEOUT) + 10)  # backstop: the network part never outlives its bound by 10 s (SIGALRM, rc 142)
    t1 = time.monotonic()
    rc = 2
    c = None
    try:
        c = context()
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
        print('p4p probe error: %s: %s' % (type(e).__name__, e), flush=True)
        rc = 2
    finally:
        if c is not None:
            c.close()
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
