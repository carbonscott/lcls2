"""Tests for calibws_server, the stand-in for the calibration constants web service
(psdaq/psdaq/sim/calibws_server.py) that drp_gpu -D epixuhr3x2 -d sim:// fetches its panel's
constants from at BeginRun.

The production client runs against it unmodified: psdaq.configdb.epixuhr_calib, through
psalg.calibdb.reader, gets the stand-in's constants, and what it hands the GPU equals what
xtc2_check expects the GPU to have applied.  No GPU and no network beyond loopback.
"""

import json
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

from psdaq.sim import calibws_server, xtc2_check

SEED = 0x1234
NPIX = 336 * 576


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The stand-in on an ephemeral loopback port, and psalg.calibdb.reader pointed at it (its
    URL is read from LCLS_CALIB_HTTP at import)."""
    reader = pytest.importorskip('psalg.calibdb.reader')
    store = calibws_server.Store('epixuhr3x2', SEED)
    log = open(tmp_path / 'calibws.jsonl', 'w')
    srv = ThreadingHTTPServer(('127.0.0.1', 0),
                              calibws_server.make_handler(store, log, threading.Lock()))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(reader, 'URL', f'http://127.0.0.1:{srv.server_port}/calib_ws')
    yield store, tmp_path / 'calibws.jsonl'
    srv.shutdown()
    srv.server_close()
    log.close()


def test_constants_are_deterministic_and_shaped():
    a, b = calibws_server.constants(SEED), calibws_server.constants(SEED)
    assert sorted(a) == sorted(calibws_server.CTYPES)
    for ct in calibws_server.CTYPES:
        assert a[ct].shape == calibws_server.SHAPE and (a[ct] == b[ct]).all()
    assert a['pedestals'].dtype == np.float32 and a['pixel_gain'].dtype == np.float32
    assert (a['pixel_gain'] > 0).all()
    # Planes differ by gain mode, so taking the wrong mode is seen
    assert (a['pedestals'][0] != a['pedestals'][1]).any()
    assert (a['pixel_gain'][0] != a['pixel_gain'][1]).any()
    bad = np.flatnonzero(a['pixel_status'][calibws_server.BAD_MODE, 0].reshape(-1))
    assert bad.size == len(range(SEED % 1013, NPIX, 1013))
    assert not a['pixel_status'][[m for m in range(8) if m != calibws_server.BAD_MODE]].any()
    assert (calibws_server.constants(SEED + 1)['pedestals'] != a['pedestals']).any()


def test_epixuhr_calib_reads_the_stand_in(server):
    """What Gpu::EpixUHR3x2::beginrun gets from psdaq.configdb.epixuhr_calib for any serial
    number is the stand-in's constants, transformed as xtc2_check expects them."""
    from psdaq.configdb import epixuhr_calib
    store, log = server
    ped_bytes, warns = epixuhr_calib.epixuhr_pedestals('SIMSERIAL', 'tstx00117', 3, [0, 1])
    assert warns == [] and ped_bytes is not None
    fac_bytes, warns = epixuhr_calib.epixuhr_gain_factors('SIMSERIAL', 'tstx00117', 3, [0, 1])
    assert warns == [] and fac_bytes is not None
    ped, fac = xtc2_check._epixuhr3x2_constants(SEED, NPIX)
    assert np.frombuffer(ped_bytes, np.float32).tobytes() == ped.tobytes()
    assert np.frombuffer(fac_bytes, np.float32).tobytes() == fac.tobytes()
    assert (fac == 0).sum() == 2 * len(range(SEED % 1013, NPIX, 1013))   # masked in both planes
    reqs = [json.loads(line) for line in open(log)]
    assert {'long': 'epixuhr3x2_SIMSERIAL'} in [r['query'] for r in reqs]
    assert all(r['status'] == 200 for r in reqs)
    assert {r['path'] for r in reqs} >= {'/calib_ws/cdb_detnames/epixuhr3x2',
                                         '/calib_ws/cdb_tstx00117/' + store.short,
                                         f'/calib_ws/cdb_{store.short}/{store.short}'}


def test_unknown_detector_has_no_constants(server):
    from psalg.calibdb import reader
    assert reader.calib_constants('epixhr2x2_SIMSERIAL', 'tstx00117', 3, ('pedestals',)) == {}


def test_check_calibrates_as_the_gpu():
    """xtc2_check's epixuhr3x2 calibration: bit 0 picks the plane (psana gain mode 0 or 1),
    bits 1-11 the value, (value - pedestal) x 1/gain (Gpu::EpixUHR3x2, pedGainCalibrate)."""
    shape, bits, calib = xtc2_check.GPU_FRAME_TYPES['epixuhr3x2']
    assert (shape, bits) == ((336, 576), 12)
    c = calibws_server.constants(SEED)
    u = np.zeros(NPIX, np.uint16)
    u[0], u[1], u[2] = 0x0fff, 0x0ffe, 0x0003
    got = calib(u, SEED)
    assert got.dtype == np.float32 and got.shape == (NPIX,)
    for i, g, v in ((0, 1, 0x7ff), (1, 0, 0x7ff), (2, 1, 1), (3, 0, 0)):
        p = c['pedestals'][g, 0].reshape(-1)[i]
        f = np.float32(1) / c['pixel_gain'][g, 0].reshape(-1)[i]
        assert got[i] == (np.float32(v) - p) * f
    bad = SEED % 1013
    assert got[bad] == 0 and got[bad + 1013] == 0
