"""pvwait: wait until PVs answer, then run a command in this process (flake register F7).

    python -m psdaq.sim.pvwait [--timeout S] PV [PV ...] -- COMMAND [ARG ...]

Gets every PV over PVA (the client configuration from the environment, as the command's own) until each has
answered once, printing one line per PV with the seconds it took, then replaces itself with COMMAND
(os.execvp), so COMMAND keeps this process's pid and its procmgr entry.  If a PV has not answered within
--timeout seconds it prints 'pvwait: timeout <PV>' for each such PV and exits 1 without running COMMAND.

Why: hpsBldCopy (psdaq/psdaq/app/hpsBldCopy.cc) polls PVBase::ready() on its input and output PVs.  ready()
is EpicsPVA::getComplete(), which waits 30 s for the PV and, if it has not connected, returns false; the
next call takes the same std::promise's future again and the program aborts with std::future_error
('Future already retrieved', signal 6).  procmgr starts bldcas, hpsBldServer and hpsBldCopy together, so a
hpsBldServer that comes up late aborts hpsBldCopy: its PVA client (pvAccessCPP 7.1.6) searches again for a
PV it has not found at about 0.24*2^n s after the start (..., 7.6, 15.2, 30.4 s), so a server that comes up more
than about 15 s after hpsBldCopy starts may not be found within the 30 s (hpsBldServer came up 16 and 18 s late in
the two runs where hpsBldCopy aborted on its own).  daq_sim starts hpsBldCopy behind this wait; the production
program is unchanged.  pvwait reads each PV once and does not re-check it: a PV whose server goes away after
that read is not covered (with bldcas stopped 20 s, hpsBldServer exits and hpsBldCopy still aborts).
"""

import argparse
import datetime
import os
import sys
import time

PVA_BIND_RACE = 'Unable to bind random UDP6 port'     # psdaq.sim.daq_sim.PVA_BIND_RACE


def command(pvs, timeout):
    """The words that run what follows them behind a wait for `pvs` (at most `timeout` s)."""
    return ['python', '-m', 'psdaq.sim.pvwait', '--timeout', str(timeout)] + list(pvs) + ['--']


def split(argv):
    """(pvwait's own arguments, the command): argv split at the first '--'."""
    if '--' not in argv:
        raise SystemExit('pvwait: no "--" before the command')
    k = argv.index('--')
    if k + 1 == len(argv):
        raise SystemExit('pvwait: no command after "--"')
    return argv[:k], argv[k + 1:]


def context(attempts=10, conf=None, who='pvwait'):
    """A PVA client context: from the environment, or from `conf` alone when it is given.  Every p4p client context
    the sim makes comes from here (daq_sim.pva_context, gui_witness.pva_context, preflight.sh's p4p probes).  PVXS
    binds the client's IPv6 search socket to the port number the kernel gave its IPv4 one, and raises
    RuntimeError(PVA_BIND_RACE) when another IPv6 UDP socket of the node holds that number: that error alone is
    retried, at most `attempts` times, with one line on stderr per retry; any other error, and the last attempt's,
    is raised."""
    from p4p.client.thread import Context
    for n in range(1, attempts + 1):
        try:
            return Context('pva') if conf is None else Context('pva', conf=conf, useenv=False)
        except RuntimeError as e:
            if str(e) != PVA_BIND_RACE or n == attempts:
                raise
            print(f'{datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")} {who}: PVA client '
                  f'context: {e} (attempt {n} of {attempts}), retrying', file=sys.stderr, flush=True)


def wait(pvs, timeout, ctx, out=sys.stdout):
    """The PVs of `pvs` that did not answer a get within `timeout` s (an empty list when all did)."""
    t0 = time.monotonic()
    pending = list(pvs)
    while pending:
        left = t0 + timeout - time.monotonic()
        if left <= 0:
            break
        got = ctx.get(pending, timeout=min(2.0, max(left, 0.1)), throw=False)
        for pv, v in zip(list(pending), got):
            if not isinstance(v, Exception):
                pending.remove(pv)
                print(f'pvwait: {pv} answered after {time.monotonic() - t0:.1f} s', file=out, flush=True)
    return pending


def main(argv=None):
    own, cmd = split(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog='pvwait')
    p.add_argument('--timeout', type=float, default=60.0, help='s to wait for all PVs (default %(default)s)')
    p.add_argument('pvs', nargs='+', metavar='PV')
    a = p.parse_args(own)
    print(f'pvwait: waiting up to {a.timeout:g} s for {" ".join(a.pvs)}', flush=True)
    ctx = context()
    try:
        missing = wait(a.pvs, a.timeout, ctx)
    finally:
        ctx.close()
    if missing:
        for pv in missing:
            print(f'pvwait: timeout {pv}', flush=True)
        return 1
    print(f'pvwait: exec {" ".join(cmd)}', flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(cmd[0], cmd)


if __name__ == '__main__':
    sys.exit(main())
