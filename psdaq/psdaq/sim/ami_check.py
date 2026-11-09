"""ami_check: give AMI a graph on a hardware-free run and check what it computed against psana2.

    python -m psdaq.sim.ami_check add   --addr tcp://127.0.0.1:<ami base port> [--det fakecam]
    python -m psdaq.sim.ami_check fetch --addr ... [--out rows.json]
    python -m psdaq.sim.ami_check check --rows rows.json --xtc2 <run .xtc2 file> [--det fakecam]

The graph (graph_nodes) takes, for every event AMI receives from the MEB, the event's id (its
timing timestamp, as psana2's evt.timestamp), the simulated detector's seq word and one pixel of
its raw array (psdaq/psdaq/sim/xtc2_check.py documents the fakecam payload: words 2 and 3 of
lane 0 are seq; word 4 depends on seed, pulse ID and lane), and keeps them in a RollingBuffer
'ami_rows'; an Accumulator 'ami_pixsum' sums the pixel over the same events.  AMI's own
reductions run in its worker, node collector and global collector, so the rows reach the
manager through the whole chain.

check reads the run's xtc2 file with psana2 and, for every event AMI kept, finds the event with
the same timestamp: it counts as matched only if its seq and pixel equal what psana2 reads.
AMI's RollingBuffer hands its collectors the worker's whole buffer at every heartbeat, so one
event's row can reach the manager more than once: identical rows count as one event, and two
rows that disagree for one timestamp fail.  It passes if AMI kept at least --min events, every
one matched, ami_count is that number and ami_pixsum equals psana2's sum of the pixel over them.  The MEB serves AMI a
subset of the events (whatever its buffers hold when AMI asks), so the counts differ from the
DAQ's; the check is per event, not a total.

The AMI source tree must be importable (PYTHONPATH, or --ami-src); psana2's calibration DB lookup
is off (skip_calib_load='all') and LCLS_CALIB_HTTP points at a dead loopback port unless set.
"""

import argparse
import json
import os
import sys
import time

GRAPH = 'graph'                         # ami's default graph name (ami.client Defaults.GraphName)
ROWS, NROWS, PIXSUM, COUNT = 'ami_rows', 'ami_rows_count', 'ami_pixsum', 'ami_count'
PIXEL = (0, 8)                          # raw[lane 0, uint16 word 8]: low half of payload word 4
MAX_ROWS = 1000000


def comm_addr(addr):
    """The manager's Comm address for a base port 'tcp://host:port' (ami.comm.Ports.Comm = +0)."""
    return addr


def graph_nodes(det='fakecam'):
    """The nodes the check adds to AMI's graph."""
    from ami.graph_nodes import Map, RollingBuffer, Accumulator
    raw = f'{det}:raw:raw'
    row, col = PIXEL

    # Built in a namespace with no module, so that dill pickles them by value: AMI's processes
    # then need nothing of psdaq to run them
    ns = {'__builtins__': __builtins__}
    seq_pixel = eval(f'lambda raw: ((int(raw[0, 4]) | (int(raw[0, 5]) << 16)), int(raw[{row}, {col}]))', ns)
    add = eval('lambda res, *values, count=1, reset=False: res + sum(values)', ns)

    return [Map(name='ami_check_seq_pixel', inputs=[raw], outputs=['ami_seq', 'ami_pixel'],
                func=seq_pixel),
            RollingBuffer(name='ami_check_rows', inputs=['eventid', 'ami_seq', 'ami_pixel'],
                          outputs=[NROWS, ROWS], N=MAX_ROWS),     # (count, buffer), as ScatterPlot
            Accumulator(name='ami_check_pixsum', inputs=['ami_pixel'], outputs=[COUNT, PIXSUM],
                        res_factory=int, reduction=add)]


def _comm(addr, timeout_ms=10000):
    """A GraphCommHandler whose requests time out (zmq.Again) instead of waiting forever for a
    manager that is not there."""
    import zmq
    from ami.comm import GraphCommHandler
    comm = GraphCommHandler(GRAPH, comm_addr(addr))
    sock = getattr(comm, '_sock', None)         # its REQ socket (ami.comm.ZmqCommHandler)
    if sock is not None:
        for opt in (zmq.RCVTIMEO, zmq.SNDTIMEO):
            sock.setsockopt(opt, timeout_ms)
        sock.setsockopt(zmq.LINGER, 0)
    return comm


def wait_sources(addr, names, timeout=60.):
    """Wait until AMI's sources include every name; return the sources (raises on timeout)."""
    import zmq
    end, sources = time.monotonic() + timeout, {}
    while True:
        try:
            with _comm(addr, 2000) as comm:
                sources = comm.sources or {}
        except zmq.Again:
            pass                        # manager not answering yet
        if all(n in sources for n in names):
            return sources
        if time.monotonic() > end:
            raise TimeoutError(f'AMI sources after {timeout:g} s: {sorted(sources)}; '
                               f'wanted {names}')
        time.sleep(0.5)


def add(addr, det='fakecam', timeout=60.):
    """Add the check's graph once AMI's worker knows the detector; True if the manager took it."""
    wait_sources(addr, [f'{det}:raw:raw', 'eventid'], timeout)
    with _comm(addr) as comm:
        ok = comm.add(graph_nodes(det))
        comm.view([ROWS, NROWS, PIXSUM, COUNT])
        return bool(ok)


def fetch(addr):
    """{'rows': [(eventid, seq, pixel), ...], 'pixsum': n, 'count': n} from AMI's manager."""
    with _comm(addr) as comm:
        rows = comm.fetch(ROWS)
        pixsum = comm.fetch(PIXSUM)
        count = comm.fetch(COUNT)
    rows = [[int(x) for x in r] for r in (rows or [])]
    return {'rows': rows, 'pixsum': None if pixsum is None else int(pixsum),
            'count': None if count is None else int(count)}


def psana_events(path, det='fakecam'):
    """{timestamp: (seq, pixel)} for every L1Accept of an xtc2 file, read with psana2."""
    os.environ.setdefault('LCLS_CALIB_HTTP', 'http://127.0.0.1:9/calib_ws')
    from psana import DataSource
    ds = DataSource(files=path, skip_calib_load='all')
    out = {}
    row, col = PIXEL
    for run in ds.runs():
        d = run.Detector(det)
        for evt in run.events():
            raw = d.raw.raw(evt)
            if raw is None:
                continue
            out[int(evt.timestamp)] = (int(raw[0, 4]) | (int(raw[0, 5]) << 16), int(raw[row, col]))
    return out


def check(ami, path, det='fakecam', minimum=100, events=None):
    """The verdict on AMI's result 'ami' (fetch()) against the xtc2 file: a dict with 'pass'.
    'events' (psana_events of the file) may be given instead of read."""
    events = psana_events(path, det) if events is None else events
    seen, problems = {}, []
    for ts, seq, pix in ami['rows']:
        if ts in seen and seen[ts] != (seq, pix):
            problems.append(f'AMI rows disagree for timestamp {ts:#x}: {seen[ts]} and {(seq, pix)}')
        seen.setdefault(ts, (seq, pix))
    rows = [(ts, seq, pix) for ts, (seq, pix) in sorted(seen.items())]
    matched, psum = 0, 0
    for ts, seq, pix in rows:
        want = events.get(ts)
        if want is None:
            problems.append(f'AMI row {ts:#x} seq {seq}: no event with that timestamp in the file')
        elif (seq, pix) != want:
            problems.append(f'AMI row {ts:#x}: seq {seq} pixel {pix}, psana2 reads seq {want[0]} '
                            f'pixel {want[1]}')
        else:
            matched += 1
            psum += pix
    if len(rows) < minimum:
        problems.append(f'AMI kept {len(rows)} events, fewer than {minimum}')
    if ami.get('count') != len(rows):
        problems.append(f'ami_count {ami.get("count")} != {len(rows)} events in AMI\'s rows')
    if ami.get('pixsum') != psum:
        problems.append(f'ami_pixsum {ami.get("pixsum")} != psana2 sum {psum} over the events AMI saw')
    seqs = sorted(s for _, s, _ in rows)
    return {'xtc2 events': len(events), 'ami rows': len(ami['rows']), 'ami events': len(rows),
            'ami matched': matched,
            'ami pixsum': ami.get('pixsum'), 'psana2 pixsum (same events)': psum,
            'ami seq range': f'{seqs[0]}..{seqs[-1]}' if seqs else None,
            'problems': problems[:5] + ([f'... {len(problems) - 5} more'] if len(problems) > 5 else []),
            'pass': not problems}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m psdaq.sim.ami_check',
                                     description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__.split('\n\n', 1)[1])
    parser.add_argument('action', choices=('add', 'fetch', 'check'))
    parser.add_argument('--addr', help='AMI manager address, tcp://127.0.0.1:<base port>')
    parser.add_argument('--det', default='fakecam')
    parser.add_argument('--ami-src', default=os.environ.get('DAQ_SIM_AMI_SRC'),
                        help='AMI source tree to import ami from (default $DAQ_SIM_AMI_SRC)')
    parser.add_argument('--out', help='fetch: write the result here (JSON)')
    parser.add_argument('--rows', help='check: a fetch result (JSON)')
    parser.add_argument('--xtc2', help='check: the run\'s xtc2 file')
    parser.add_argument('--min', type=int, default=100, help='check: rows AMI must keep (default %(default)d)')
    args = parser.parse_args(argv)
    if args.ami_src:
        sys.path.insert(0, args.ami_src)
    if args.action == 'add':
        print('graph added' if add(args.addr, args.det) else 'graph NOT added')
        return 0
    if args.action == 'fetch':
        res = fetch(args.addr)
        text = json.dumps(res)
        if args.out:
            with open(args.out, 'w') as f:
                f.write(text)
        print(f'{len(res["rows"])} rows, pixsum {res["pixsum"]}, count {res["count"]}')
        return 0
    with open(args.rows) as f:
        res = check(json.load(f), args.xtc2, args.det, args.min)
    print(json.dumps(res))
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
