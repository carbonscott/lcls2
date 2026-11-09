"""Tests for the hardware-free XpmDetector types' data and configs (psdaq/psdaq/sim):
the epixhremu frame file and what EpixHRemu records from it, and the config DB entries
configdb_seed stores for cspad, epixhremu, jungfrauemu and ts."""

import json

import numpy as np
import pytest

from psdaq.sim import epixhremu_frame, pattern


def test_epixhremu_expected_is_the_first_192_of_each_frame_row_in_every_asic():
    seed = 0x5a3c
    frame = epixhremu_frame.frame(seed)
    assert frame.shape == (288, 384) and frame.dtype == np.uint16
    assert frame.flat[7] == int(pattern.pattern(seed, 0, 7, 16))
    want = epixhremu_frame.expected(seed)
    assert want.shape == (144, 768)
    for a in range(4):                                      # EpixHRemu::event's copy
        assert (want[:, a * 192:(a + 1) * 192] == frame[:144, :192]).all()
    assert not (epixhremu_frame.expected(seed, offset=1) == want).all()
    assert epixhremu_frame.expected(seed, nlanes=2).shape == (144, 1536)


def test_epixhremu_frame_file_reads_back(tmp_path):
    pytest.importorskip('psana')
    from psana import DataSource
    path = str(tmp_path / 'frame.xtc2')
    epixhremu_frame.write(path, 0x1234)
    ds = DataSource(files=[path], skip_calib_load='all')
    run = next(ds.runs())
    evts = list(run.events())
    assert len(evts) == 1
    # the dgram's own view (psana has no epixhr2x2 raw 2.0.0 interface; EpixHRemu reads the
    # 'raw' uint16 rank-2 array of the first L1Accept, whatever its detector)
    raw = evts[0]._dgrams[0].epixhr[0].raw.raw
    assert raw.dtype == np.uint16 and (raw == epixhremu_frame.frame(0x1234)).all()


@pytest.mark.parametrize('det_type', ['cspad', 'epixhremu', 'jungfrauemu'])
def test_xpmdet_types_store_a_sim_seed(det_type):
    pytest.importorskip('psdaq.configdb.typed_json')
    from psdaq.sim.configdb_seed import XPMDET_TYPES, fakecam_cdict
    assert det_type in XPMDET_TYPES
    top = json.loads(json.dumps(fakecam_cdict(det_type, 0, 0x77, 64, det_type).typed_json()))
    assert top['detType:RO'] == det_type and top['user']['sim_seed'] == 0x77


def test_ts_stores_its_own_beam_config():
    pytest.importorskip('psdaq.configdb.ts_config_store')
    from psdaq.sim.configdb_seed import type_cdict
    top = json.loads(json.dumps(type_cdict('ts', 'ts', 0).typed_json()))
    assert top['detType:RO'] == 'ts'
    assert top['user']['LINAC'] == 0 and top['user']['Cu']['group0_eventcode'] == 40
    assert top['expert']['group0']['inhibit3']['interval'] == 1


def test_epixm320_store_from_the_firmware_project_dir():
    """epixm320_cdict takes the firmware project's software/config (its __main__'s --dir)."""
    import os
    if not os.environ.get('SUBMODULEDIR'):
        pytest.skip('needs $SUBMODULEDIR (the DAQ env)')
    from psdaq.sim.configdb_seed import STORE_DIR, type_cdict
    assert STORE_DIR['epixm320'] == 'epix-hr-m-320k/software/config'
    top = json.loads(json.dumps(type_cdict('epixm320', 'epixm320', 0).typed_json()))
    assert top['detType:RO'] == 'epixm320' and top['user']['asic_enable'] == 0xf
