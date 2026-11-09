"""psdaq.sim.sim_path: packages in $PSDAQ_SIM_PYTHONPATH import from there first, whatever
pyrogue.addLibraryPath later puts at sys.path[0]; unset, nothing changes."""
import importlib
import sys

from psdaq.sim import sim_path


def _pkg(root, name, tag):
    d = root / name
    d.mkdir(parents=True)
    (d / '__init__.py').write_text('TAG = %r\n' % tag)
    (d / 'sub.py').write_text('TAG = %r\n' % tag)
    return str(root)


def _cleanup(name):
    for k in [k for k in sys.modules if k == name or k.startswith(name + '.')]:
        del sys.modules[k]


def test_pinned_package_wins_over_sys_path_front(tmp_path, monkeypatch):
    name = 'simpath_probe_pkg'
    pinned = _pkg(tmp_path / 'pinned', name, 'pinned')
    bundled = _pkg(tmp_path / 'bundled', name, 'bundled')
    monkeypatch.setenv('SIMPATH_TEST_ROOT', str(tmp_path))
    try:
        assert sim_path.pin('$SIMPATH_TEST_ROOT/pinned') == [pinned]
        monkeypatch.setattr(sys, 'path', [bundled] + sys.path)   # what addLibraryPath does
        _cleanup(name)
        assert importlib.import_module(name).TAG == 'pinned'
        assert importlib.import_module(name + '.sub').TAG == 'pinned'
    finally:
        sim_path.pin('')
        _cleanup(name)


def test_unset_changes_nothing(tmp_path, monkeypatch):
    name = 'simpath_probe_pkg2'
    bundled = _pkg(tmp_path / 'bundled', name, 'bundled')
    monkeypatch.delenv(sim_path.ENV, raising=False)
    try:
        assert sim_path.pin() == []
        monkeypatch.setattr(sys, 'path', [bundled] + sys.path)
        _cleanup(name)
        assert importlib.import_module(name).TAG == 'bundled'
    finally:
        _cleanup(name)
