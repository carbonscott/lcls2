"""calibws_server: a stand-in, on loopback, for the calibration constants web service (calib_ws)
that psalg.calibdb.reader queries.  The GPU DRP of the ePixUHR 3x2 fetches its panel's constants
there at BeginRun (Gpu::EpixUHR3x2::beginrun -> psdaq.configdb.epixuhr_calib ->
psalg.calibdb.calib_constants); daq_sim up starts this for it and points the DRP's
LCLS_CALIB_HTTP here, so that code runs unmodified and contacts no real service.

    python -m psdaq.sim.calibws_server --port P [--seed S] [--det-type epixuhr3x2] [--log F]

It answers the three requests psalg.calibdb.reader makes (its URL is LCLS_CALIB_HTTP + /calib_ws):
  GET cdb_detnames/<type>?query_string={"long": "<type>_<serial>"}
      -> [{"long": <that>, "short": "<type>_000001"}], for any serial (the log says which)
  GET cdb_<db>/<short>?query_string={"detector": <short>[, "ctype": <c>]}
      -> in the detector's database (cdb_<short>), one document per constant type, valid for
         runs 0..end; an experiment's database (any other cdb_<db>) has none
  GET cdb_<short>/gridfs/<id>
      -> the array's bytes
The constants are constants(seed): arrays of shape SHAPE, one plane per psana gain mode, of
pedestals (float32), pixel_gain (float32, ADU/keV) and pixel_status (uint64: one pixel in 1013
is bad in gain mode 2), each a function of seed, mode and pixel, so a check can make them again.
Every request is one JSON line in --log.  It binds 127.0.0.1 only.
"""

import argparse
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

SHAPE = (8, 1, 336, 576)        # psana's (gain modes, segments, rows, columns) of an ePixUHR 3x2
SHORT_ID = 1                    # The short name's number: <type>_000001
CTYPES = ('pedestals', 'pixel_gain', 'pixel_status')
BAD_PERIOD = 1013               # pixel_status: pixel i is bad in gain mode 2 when i % 1013 == seed % 1013
BAD_MODE = 2


def _hash(seed, salt):
    """uint64 (modes, pixels): a mix of pixel index, gain mode, seed and salt."""
    npix = SHAPE[2] * SHAPE[3]
    i = np.arange(npix, dtype=np.uint64)[None, :]
    m = np.arange(SHAPE[0], dtype=np.uint64)[:, None]
    h = i * np.uint64(0x9E3779B1) + m * np.uint64(0x85EBCA77) + np.uint64((seed * 31 + salt) & 0xffffffff)
    return h ^ (h >> np.uint64(15))


def constants(seed):
    """{ctype: ndarray of SHAPE}: what this stand-in serves for the seed."""
    npix = SHAPE[2] * SHAPE[3]
    ped = (100 + _hash(seed, 1) % np.uint64(400)).astype(np.float32) / np.float32(4)  # 25 .. 124.75
    gain = (1 + _hash(seed, 2) % np.uint64(16)).astype(np.float32) / np.float32(8)    # 0.125 .. 2
    status = np.zeros((SHAPE[0], npix), dtype=np.uint64)
    status[BAD_MODE, np.arange(npix) % BAD_PERIOD == seed % BAD_PERIOD] = 1
    return {'pedestals': ped.reshape(SHAPE), 'pixel_gain': gain.reshape(SHAPE),
            'pixel_status': status.reshape(SHAPE)}


class Store:
    def __init__(self, det_type, seed):
        self.det_type = det_type
        self.short = f'{det_type}_{SHORT_ID:06d}'
        self.arrays = constants(seed)
        t = int(time.time())
        self.docs = []
        for k, ct in enumerate(CTYPES):
            a = self.arrays[ct]
            oid = f'{t:08x}{k + 1:016x}'                # A MongoDB ObjectId: creation time first
            self.docs.append({'_id': oid, 'ctype': ct, 'detector': self.short, 'run': '0',
                              'run_end': 'end', 'experiment': 'simcalib', 'data_type': 'ndarray',
                              'data_dtype': str(a.dtype), 'data_shape': str(tuple(a.shape)),
                              'id_data': f'{t:08x}{k + 101:016x}'})
        self.blobs = {d['id_data']: self.arrays[d['ctype']].tobytes() for d in self.docs}


def make_handler(store, log, lock):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):      # Requests go to the JSON log instead
            pass

        def _send(self, code, body, ctype='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            parts = [p for p in url.path.split('/') if p]
            qs = urllib.parse.parse_qs(url.query).get('query_string', [None])[0]
            try:
                query = json.loads(qs) if qs else {}
            except ValueError:
                query = None
            code, body, ctype, served = 404, b'[]', 'application/json', None
            if query is not None and len(parts) == 3 and parts[0] == 'calib_ws':
                db, col = parts[1], parts[2]
                if db == 'cdb_detnames' and col == store.det_type:
                    long = query.get('long', '')
                    docs = ([{'long': long, 'short': store.short}]
                            if isinstance(long, str) and long.startswith(store.det_type + '_') else [])
                    code, body, served = 200, json.dumps(docs).encode(), [d['short'] for d in docs]
                elif db == f'cdb_{store.short}' and col == store.short:
                    docs = [d for d in store.docs
                            if all(d.get(k) == v for k, v in query.items())]
                    code, body, served = 200, json.dumps(docs).encode(), [d['ctype'] for d in docs]
                elif db.startswith('cdb_') and col == store.short:
                    code, body, served = 200, b'[]', []          # an experiment's database: none
            elif len(parts) == 4 and parts[0] == 'calib_ws' and parts[2] == 'gridfs' and \
                    parts[1] == f'cdb_{store.short}' and parts[3] in store.blobs:
                code, body, ctype = 200, store.blobs[parts[3]], 'application/octet-stream'
                served = f'{len(body)} B'
            self._send(code, body, ctype)
            with lock:
                log.write(json.dumps({'t': time.time(), 'path': url.path, 'query': query,
                                      'status': code, 'served': served}) + '\n')
                log.flush()

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--port', type=int, required=True, help='TCP port on 127.0.0.1')
    p.add_argument('--seed', type=lambda s: int(s, 0), default=0x1234,
                   help='the constants\' seed (default %(default)#x)')
    p.add_argument('--det-type', default='epixuhr3x2', help='detector type (default %(default)s)')
    p.add_argument('--log', default=None, help='JSON lines, one per request (default: stdout)')
    args = p.parse_args(argv)
    store = Store(args.det_type, args.seed)
    log = open(args.log, 'a') if args.log else sys.stdout
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(store, log, threading.Lock()))
    srv.daemon_threads = True
    print(f'calibws: ready on 127.0.0.1:{args.port}: {store.short} ({", ".join(CTYPES)} of shape '
          f'{SHAPE}, seed {args.seed:#x}) for any {args.det_type}_<serial>', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
