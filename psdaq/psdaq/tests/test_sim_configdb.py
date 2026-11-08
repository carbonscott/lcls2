"""Tests for the local config DB stand-in (psdaq.sim.configdb_server).

Everything runs against a server bound to 127.0.0.1 in this process, through
the real HTTP client psdaq.configdb.configdb, with the proxy variables set
the way the hardware-free DAQ sets them (anything not local fails closed).
"""

import ast
import datetime
import json
import os
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("requests")
pytest.importorskip("krtc")

import psdaq
from psdaq.configdb.configdb import configdb
from psdaq.configdb.get_config import get_config, get_config_with_params
from psdaq.configdb.typed_json import cdict
from psdaq.sim import configdb_server, configdb_seed


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")


@pytest.fixture
def server(tmp_path, local_env):
    store = str(tmp_path / "configdb.json")
    srv = configdb_server.make_server(store, access_log=str(tmp_path / "access.jsonl"))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield configdb_server.server_url(srv), store, srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def _control_dummy_trigger_body():
    """The trigger body control.py uses when it has no config DB (--sim)."""
    path = os.path.join(os.path.dirname(psdaq.__file__), "control", "control.py")
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == "trigger_body" for t in node.targets)):
            return ast.literal_eval(node.value)
    raise AssertionError("no literal trigger_body in control.py")


def test_save_get_round_trip(server):
    url, store, _ = server
    db = configdb(url, "tst", create=True, root="configDB")
    db.add_alias("BEAM")
    db.add_device_config("fakecam")
    top = cdict()
    top.setAlg("fakecam", [0, 0, 1])
    top.set("user.sim_seed", 7, "UINT32")
    top.setInfo("fakecam", "cam", 0, "id0", "doc")
    key = db.modify_device("BEAM", top)
    assert key == 1                                   # add_alias took key 0

    got = db.get_configuration("BEAM", "cam_0")
    assert got == json.loads(json.dumps(top.typed_json()))
    assert db.get_configuration(str(key), "cam_0") == got   # by key, as `configdb cat --key`
    assert db.get_key("BEAM") == key
    assert db.get_devices("BEAM") == ["cam_0"]
    assert db.get_aliases() == ["BEAM"]
    assert db.get_hutches() == ["tst"]
    assert db.get_device_configs() == ["fakecam"]

    # an identical save is refused, like mongoconfigdb
    with pytest.raises(Exception):
        db.modify_device("BEAM", top)

    # the file store survives a restart
    reopened = configdb_server.JsonConfigStore(store)
    assert reopened.get_configuration(reopened._root("configDB"), "tst", "BEAM", "cam_0") == got


def test_mongoconfigdb_semantics(server):
    """test_configdb.py's mongoconfigdb sequence, through HTTP."""
    url, _, _ = server
    c = configdb(url, "AMO", create=True, root="regress")
    c.add_alias("BEAM")                 # 0
    c.add_alias("NOBEAM")               # 1
    c.add_device_config("evr")
    c.add_device_config("jungfrau")
    e = cdict()
    e.set("a:RO", 32)
    e.set("b", 74)
    e.setInfo(detType="evr", detName="evr0")
    j = cdict()
    j.set("c", 93)
    j.set("d", 67)
    j.set("e", [3, 6.5, 9.4], "DOUBLE")
    j.setInfo(detType="jungfrau", detName="jungfrau0")
    c.modify_device("BEAM", e)          # 2
    c.modify_device("BEAM", j)          # 3
    with pytest.raises(Exception):
        c.modify_device("BEAM", e)
    j.set("c", 103)
    c.modify_device("NOBEAM", j)        # 4
    for alias, key, cval in (("BEAM", 3, 93), ("NOBEAM", 4, 103)):
        assert c.get_key(alias) == key
        assert c.get_configuration(str(key), "jungfrau0")["c"] == cval
    j.set("d", 73)
    c.modify_device("BEAM", j)          # 5
    h = c.get_history("BEAM", "jungfrau0", ["d", "e"])["value"]
    assert [67, 73] == [d["d"] for d in h]
    assert [3, 5] == [d["key"] for d in h]
    assert h[0]["e"] == [3, 6.5, 9.4]
    datetime.datetime.fromisoformat(h[0]["date"])   # what `configdb history` parses

    c.rename_device("BEAM", "evr0", "evr7")
    assert c.get_configuration("BEAM", "evr7")["b"] == 74
    assert c.get_configuration("BEAM", "evr7")["detName:RO"] == "evr7"
    with pytest.raises(Exception):
        c.remove_device("BEAM", "evr6")
    c.remove_device("BEAM", "evr7")
    with pytest.raises(Exception):
        c.get_configuration("BEAM", "evr7")
    assert "AMO" in c.get_hutches()


def test_control_trigger_fetch(server):
    """The exact call control.py makes at Configure, against a seeded DB."""
    url, _, _ = server
    result = configdb_seed.seed(url)
    assert result["tmoteb_0"][1] and result["fakecam_0"][1]
    assert all(not changed for _, changed in configdb_seed.seed(url).values())  # idempotent

    cfg_dbase = url + "configDB"                       # control.py -d
    [db_url, db_name] = cfg_dbase.rsplit("/", 1)       # control.py condition_configure
    trigger_body = get_config_with_params(db_url, "tst", db_name, "BEAM", "tmoteb" + "_0")
    assert trigger_body["persistValue"] == 0xdeadbeef
    for k, v in _control_dummy_trigger_body().items():
        assert trigger_body[k] == v, k


def test_drp_get_config(server):
    """The call a DRP's python config script makes (get_config.get_config)."""
    url, _, _ = server
    configdb_seed.seed(url, sim_seed=0xabcd)
    connect_json = json.dumps({"body": {"control": {"0": {"control_info": {
        "instrument": "tst", "cfg_dbase": url + "configDB"}}}}})
    cfg = get_config(connect_json, "BEAM", "fakecam", 0)
    assert cfg["user"]["sim_seed"] == 0xabcd
    assert cfg["detType:RO"] == "fakecam"


def test_webconfigdb_history_string_body(server):
    from psdaq.configdb import webconfigdb
    url, _, _ = server
    configdb_seed.seed(url)
    h = webconfigdb.configdb(url, "tst", root="configDB").get_history(
        "BEAM", "tmoteb_0", ["persistValue"])
    assert h["value"][0]["persistValue"] == 0xdeadbeef


def test_access_log_and_errors(server, tmp_path):
    url, _, _ = server
    db = configdb(url, "tst", create=True, root="configDB")
    with pytest.raises(RuntimeError):
        db.get_configuration("NOPE", "x_0")
    lines = [json.loads(l) for l in open(tmp_path / "access.jsonl")]
    assert lines[0]["path"] == "/ws/configDB/create_collections/tst/"
    assert lines[-1]["success"] is False


def test_cli_server_and_configdb_cli(tmp_path, local_env):
    url_file = tmp_path / "url"
    proc = subprocess.Popen([sys.executable, "-m", "psdaq.sim.configdb_server",
                             "--store", str(tmp_path / "db.json"), "--url-file", str(url_file)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(100):
            if url_file.exists() and url_file.read_text().strip():
                break
            time.sleep(0.1)
        url = url_file.read_text().strip()
        assert url.startswith("http://127.0.0.1:")
        seed = subprocess.run([sys.executable, "-m", "psdaq.sim.configdb_seed", "--url", url],
                              capture_output=True, text=True, timeout=60)
        assert seed.returncode == 0, seed.stderr
        assert "tst/BEAM/tmoteb_0 key=1 written" in seed.stdout
        ls = subprocess.run([sys.executable, "-m", "psdaq.configdb.configdb", "--url", url,
                             "ls", "tst/BEAM"], capture_output=True, text=True, timeout=60)
        assert ls.stdout.split() == ["fakecam_0", "tmoteb_0"], ls.stderr
    finally:
        proc.terminate()
        proc.wait(10)
    assert proc.returncode == 0
