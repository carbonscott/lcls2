"""
Sim-only import path override for firmware python packages: $PSDAQ_SIM_PYTHONPATH.

A type's config module puts its firmware package's bundled libraries on sys.path through
psdaq.utils.enable_<package> (pyrogue.addLibraryPath inserts each at sys.path[0]), and some
modules import packages that no enable_* module provides.  When the bundled copy does not work
with this env's rogue, or a package is missing from the path, set

    PSDAQ_SIM_PYTHONPATH=<dir>[:<dir>...]     ($VARS such as $SUBMODULEDIR are expanded)

and every top-level package found in those directories is imported from there first, whatever
sys.path says.  Sub-packages follow their package.  Unset or empty: nothing changes.

pin() runs before a config module is imported: in rogue_dev.install (the DRP's and rogue_drive's
sim:// hook) and in configdb_seed.type_cdict.  Only the simulated DAQ calls it.
"""

import importlib.machinery
import os
import sys

ENV = 'PSDAQ_SIM_PYTHONPATH'


class _Pinned:
    """A meta path finder that looks up top-level names in its directories before sys.path."""

    def __init__(self, paths):
        self.paths = paths

    def find_spec(self, name, path=None, target=None):
        if '.' in name:
            return None
        return importlib.machinery.PathFinder.find_spec(name, self.paths)


def paths(value=None):
    value = os.environ.get(ENV, '') if value is None else value
    return [os.path.expandvars(p) for p in value.split(':') if p]


def pin(value=None):
    """Install (or update) the finder for $PSDAQ_SIM_PYTHONPATH; returns the directories."""
    ps = paths(value)
    for f in sys.meta_path:
        if isinstance(f, _Pinned):
            f.paths = ps
            return ps
    if ps:
        sys.meta_path.insert(0, _Pinned(ps))
    return ps
