"""Tests for psdaq.sim.pvwait (flake register F7), without a network: its command words, how daq_sim puts them
before hpsBldCopy, that coverage still names hpsBldCopy as the program of that command line, and that the wait
gives up after its timeout with the PVs that did not answer."""

import io

import pytest

from psdaq.sim import coverage, daq_sim, gui_witness, pvwait


def test_hpsbldcopy_waits_for_its_five_pvs():
    ports = {'reg': 1, 'diag': 2, 'bld': 3, 'bldcas': 4, 'search': 5, 'svc': 6}
    argv = gui_witness.hps_argv('hpsBldCopy', 'DAQ:SIM', ports)
    words = daq_sim.hps_pvwait(argv)
    assert words == ['python', '-m', 'psdaq.sim.pvwait', '--timeout', str(daq_sim.HPS_PV_WAIT),
                     'DAQ:SIM:HPSEX:PAYLOAD', 'DAQ:SIM:HPSEX:ADDR', 'DAQ:SIM:HPSEX:PORT',
                     'DAQ:SIM:HPSCPA:ADDR', 'DAQ:SIM:HPSCPA:PORT', '--']
    own, cmd = pvwait.split(words[3:] + ['hpsBldCopy'] + argv)
    assert cmd == ['hpsBldCopy'] + argv
    assert coverage.resolve(' '.join(words + ['hpsBldCopy'] + argv)) == ('hpsBldCopy', argv)
    assert coverage.resolve('python -m psdaq.sim.pvwait A') == ('pvwait', ['A'])     # no '--': itself


def test_split_needs_a_command():
    with pytest.raises(SystemExit):
        pvwait.split(['A', 'B'])
    with pytest.raises(SystemExit):
        pvwait.split(['A', '--'])


class Ctx:
    """A client context whose PVs in `up` answer and the others time out."""
    def __init__(self, up):
        self.up = up

    def get(self, names, timeout, throw):
        return [1 if n in self.up else TimeoutError(n) for n in names]


def test_wait_returns_the_pvs_that_never_answered():
    out = io.StringIO()
    assert pvwait.wait(['A', 'B'], 0.3, Ctx({'A'}), out) == ['B']
    assert 'pvwait: A answered after' in out.getvalue()
    assert pvwait.wait(['A', 'B'], 0.3, Ctx({'A', 'B'}), io.StringIO()) == []
