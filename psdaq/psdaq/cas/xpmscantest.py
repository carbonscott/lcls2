"""XPM step-scan test script written against an older `DaqPVA` interface."""
import sys
import socket
import argparse
from psdaq.control.control import DaqPVA
from threading import Thread, Event, Condition, Timer
import logging

class ScanControl(object):

    """Set up step-scan PVs, a repeating message-insert timer and a StepDone monitor through `DaqPVA`.

    It calls ``DaqPVA(platform=..., xpm_master=..., pv_base=...)`` and uses attributes such
    as `pvStepGroups`; the current `DaqPVA` in `psdaq.control.control` takes only
    `report_error`, so construction raises TypeError.
    """
    def __init__(self,args):

        self.args = args
        self.pva = DaqPVA(platform=args.p, xpm_master=args.x, pv_base='DAQ:LAB2')

        self.groups = int(1<<args.p)
        self.pva.pv_put(self.pva.pvStepGroups  ,self.groups)

        def expired():
            self.pva.pv_put(self.pva.pvGroupMsgInsert, self.groups)
            self.transitions = Timer(args.t,expired)
            self.transitions.start()

        self.transitions = Timer(args.t,expired)
        self.transitions.start()

        self.step_done = Event()

        def callback(done):
            logging.debug(f'callback {done}')
            if int(done):
                self.step_done.set()

        self.pva.monitor_StepDone(callback=callback)

    def run(self):
        """Reset L0 for the group, then for each of `args.s` steps set StepEnd to ``(i+1)*args.e``, clear StepDone, enable L0 and wait for the step-done event."""
        self.pva.pv_put(self.pva.pvGroupL0Reset,self.groups)
        for i in range(self.args.s):
            logging.debug(f'begin step {i}')
            self.step_done.clear()
            self.pva.pv_put(self.pva.pvStepEnd , (i+1)*self.args.e)
            self.pva.pv_put(self.pva.pvStepDone, 0)
            self.pva.pv_put(self.pva.pvGroupL0Enable, self.groups)
            self.step_done.wait()
            logging.debug(f'end step {i}')

def main():

    """Parse -x, -p, -e, -s, -r, -t, -n, enable DEBUG logging and call `ScanControl.run` `n` times."""
    parser = argparse.ArgumentParser(description='xpm scan test')
    parser.add_argument('-x', metavar='XPM', type=int, default=3,
                        help='master XPM')
    parser.add_argument('-p', metavar='PART',type=int, choices=range(0, 8), default=0,
                        help='partition (default 0)')
    parser.add_argument('-e', metavar='EVENTS', type=int, default=1000, help='event per step')
    parser.add_argument('-s', metavar='STEPS', type=int, default=1000, help='steps')
    parser.add_argument('-r', metavar='RATE', type=int, default=0, help='rate')
    parser.add_argument('-t', metavar='TIMER', type=float, default=1.0, help='timer')
    parser.add_argument('-n', metavar='NCYCLE', type=int, default=50, help='ncycles')

    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG)

    c = ScanControl(args)
    for i in range(args.n):
        c.run()

if __name__ == '__main__':
    main()
