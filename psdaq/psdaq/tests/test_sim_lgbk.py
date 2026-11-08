"""Tests for the local run database / eLog stand-in (psdaq.sim.lgbk_server).

The requests are made by control.py's own CollectionManager methods, bound
to a small stand-in object, so the URLs, methods and response handling are
exactly the ones the DAQ uses in normal mode.
"""

import json
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("zmq")
pytest.importorskip("p4p")
requests = pytest.importorskip("requests")
control = pytest.importorskip("psdaq.control.control")

from psdaq.sim import lgbk_server

PASSWORD = "not-a-real-password"


class Collection(object):
    """The attributes control.py's run DB methods read, and nothing else."""
    simulator = False
    instrument = "tst"
    station = 5
    user = "tstopr"
    password = PASSWORD
    defaultRunType = "DATA"
    runType = "DATA"
    experiment_name = None

    def __init__(self, url):
        self.url = url
        self.errors = []
        self.published = []
        self.front_pub = SimpleNamespace(send_json=self.published.append)

    def report_error(self, msg):
        self.errors.append(msg)


for _name in ("get_experiment", "get_last_run_number", "start_run", "add_run_params",
              "add_update_run_param_descriptions", "end_run", "register_file"):
    setattr(Collection, _name, getattr(control.CollectionManager, _name))


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")


@pytest.fixture
def server(tmp_path, local_env):
    log = tmp_path / "lgbk.jsonl"
    srv = lgbk_server.make_server({"tst": "tstx00001"}, str(tmp_path / "lgbk.json"), str(log))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield lgbk_server.server_url(srv), log, srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def test_control_run_cycle(server):
    url, log, srv = server
    c = Collection(url)

    exp = c.get_experiment()
    assert exp == "tstx00001"
    c.experiment_name = exp
    assert c.get_last_run_number() == 0

    assert c.start_run(exp) == 1
    assert c.add_run_params(exp, {"DAQ Detectors/drp/fakecam": "0"}) == 1
    assert c.add_update_run_param_descriptions(exp, {"TST:PV": "a PV"}) == 1
    path = "/tmp/tst/tstx00001/xtc/tstx00001-r0001-s000-c000.xtc2"
    c.register_file({"path": path, "absolute_path": path, "hostname": "localhost",
                     "gen": 2, "run_num": 1})
    c.end_run(exp)
    assert c.errors == []
    assert c.get_last_run_number() == 1
    c.runType = "TEST"
    assert c.start_run(exp) == 2
    assert c.runType == "DATA"             # control.py reverts it after each start_run

    run1 = srv.db.runs(exp)[0]
    assert run1["params"] == {"DAQ Detectors/drp/fakecam": "0"}
    assert run1["files"][0]["path"] == path and run1["end_time"] is not None
    assert srv.db.runs(exp)[1]["type"] == "TEST"
    assert c.published[0]["header"]["key"] == "fileReport"

    text = log.read_text()
    assert PASSWORD not in text
    calls = [(r["method"], r["path"].split("?")[0].replace("//", "/"), r["user"])
             for r in map(json.loads, text.splitlines())]
    assert calls == [
        ("GET", "/lgbk/ws/activeexperiment_for_instrument_station", None),
        ("GET", "/lgbk/tstx00001/ws/current_run", None),
        ("POST", "/run_control/tstx00001/ws/start_run", "tstopr"),
        ("POST", "/run_control/tstx00001/ws/add_run_params", "tstopr"),
        ("POST", "/run_control/tstx00001/ws/add_update_run_param_descriptions", "tstopr"),
        ("POST", "/lgbk/tstx00001/ws/register_file", "tstopr"),
        ("POST", "/run_control/tstx00001/ws/end_run", "tstopr"),
        ("GET", "/lgbk/tstx00001/ws/current_run", None),
        ("POST", "/run_control/tstx00001/ws/start_run", "tstopr"),
    ]


def test_state_survives_restart(server, tmp_path):
    url, _, _ = server
    c = Collection(url)
    assert c.start_run("tstx00001") == 1
    db = lgbk_server.RunDb({"tst": "tstx00001"}, str(tmp_path / "lgbk.json"))
    assert db.runs("tstx00001")[0]["num"] == 1


def test_unknown_instrument_and_experiment(server):
    url, _, _ = server
    c = Collection(url)
    c.instrument = "xyz"
    assert c.get_experiment() is None
    with pytest.raises(Exception, match="start_run error"):
        c.start_run("nosuchexp")
    assert "status code 404" in c.errors[-1]
    c.experiment_name = "nosuchexp"
    with pytest.raises(control.ConfigDBError):
        c.register_file({"path": "/x"})


def test_non_local_url_fails_closed(local_env):
    # The proxy variables route any non-local host to a closed local port...
    proxies = requests.utils.get_environ_proxies("https://pswww.slac.stanford.edu/ws/lgbk/")
    assert proxies.get("https") == "http://127.0.0.1:9"
    # ...so a forgotten --url fails instead of reaching a facility service.
    c = Collection("https://pswww.invalid/ws-auth/devlgbk/")
    assert c.get_experiment() is None
