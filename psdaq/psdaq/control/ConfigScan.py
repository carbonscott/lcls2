"""ConfigScan helper class that steps the DAQ through a scan via a control object."""
import logging
import zmq
from threading import Thread, Event, Condition
import json as oldjson
from psdaq.control.ControlDef import ControlDef, front_pub_port, front_rep_port, create_msg

class ConfigScan:
    """Run DAQ scan steps through a control object using two threads.

    On construction it binds/connects an inproc PUSH/PULL socket pair
    ('inproc://config_scan') and starts `daq_communicator_thread` (non-daemon) and
    `daq_monitor_thread` (daemon). `control` must provide `setState`, `monitorStatus` and
    `getBlock`; `args` must have attributes v, detname, scantype and run_type.
    """
    def __init__(self, control, *, daqState, args):
        self.control = control
        self.name = 'mydaq'
        self.parent = None
        self.context = zmq.Context()
        self.push_socket = self.context.socket(zmq.PUSH)
        self.push_socket.bind('inproc://config_scan')
        self.pull_socket = self.context.socket(zmq.PULL)
        self.pull_socket.connect('inproc://config_scan')
        self.comm_thread = Thread(target=self.daq_communicator_thread, args=())
        self.mon_thread = Thread(target=self.daq_monitor_thread, args=(), daemon=True)
        self.ready = Event()
        self.step_done = Event()
        self.daqState = daqState
        self.args = args
        self.daqState_cv = Condition()
        self.stepDone_cv = Condition()
        self.stepDone = 0
        self.comm_thread.start()
        self.mon_thread.start()
        self.verbose = args.v
        self.motors = []                # set in configure()
        self._step_count = 0
        self.detname = args.detname
        self.scantype = args.scantype

    # this thread tells the daq to do a step and waits for the completion
    def daq_communicator_thread(self):
        """Loop forever, acting on state strings received on the inproc PULL socket.

        Each message is split on the first ',' into a state and an optional JSON phase1 part.
        For 'connected'/'starting' it calls `control.setState` (with the parsed phase1 if
        present), waits until `daqState` matches and sets `ready`. For 'running' it adds
        ``args.run_type`` (if not None) to phase1, calls `setState`, waits for 'running' and then
        for the `step_done` event; 'shutdown' ends the loop and other input is ignored.
        """
        logging.debug('*** daq_communicator_thread')
        while True:
            sss = self.pull_socket.recv().decode("utf-8")
            if ',' in sss:
                state, phase1 = sss.split(',', maxsplit=1)
            else:
                state, phase1 = sss, None

            logging.debug('*** received %s' % state)
            if state in ('connected', 'starting'):
                # send 'daqstate(state)' and wait for complete
                if phase1 is None:
                    errMsg = self.control.setState(state)
                else:
                    errMsg = self.control.setState(state, oldjson.loads(phase1))

                if errMsg is not None:
                    logging.error('%s' % errMsg)
                    continue

                with self.daqState_cv:
                    while self.daqState != state:
                        logging.debug('daqState \'%s\', waiting for \'%s\'...' % (self.daqState, state))
                        self.daqState_cv.wait(1.0)
                    logging.debug('daqState \'%s\'' % self.daqState)

                self.ready.set()

            elif state=='running':
                # launch the step with 'daqstate(running)' (with the
                # scan values for the daq to record to xtc2).

                # set DAQ state
                if phase1 is None and self.args.run_type is None:
                    errMsg = self.control.setState(state)
                else:
                    phase1_dict = {}
                    if phase1 is not None:
                        phase1_dict.update(oldjson.loads(phase1))
                    if self.args.run_type is not None:
                        phase1_dict.update({"run_type": self.args.run_type})
                    errMsg = self.control.setState(state, phase1_dict)
                if errMsg is not None:
                    logging.error('%s' % errMsg)
                    continue

                # wait for running
                with self.daqState_cv:
                    while self.daqState != 'running':
                        logging.debug('daqState \'%s\', waiting for \'running\'...' % self.daqState)
                        self.daqState_cv.wait(1.0)
                    logging.debug('daqState \'%s\'' % self.daqState)

                # wait for step done
                logging.debug('Waiting for step done...')
                self.step_done.wait()
                self.step_done.clear()
                logging.debug('step done.')

            elif state=='shutdown':
                break

    def daq_monitor_thread(self):
        """Loop forever, tracking DAQ state from `control.monitorStatus()`.

        Stops when the first returned part is None; sets the `step_done` event on 'step';
        ignores other parts not in `ControlDef.transitions`. For transitions it sets
        `daqState` to the second part and notifies `daqState_cv`.
        """
        logging.debug('*** daq_monitor_thread')
        while True:
            part1, part2, part3, part4, part5, part6, part7, part8 = self.control.monitorStatus()
            if part1 is None:
                break
            elif part1 == 'step':
                self.step_done.set()
                continue
            elif part1 not in ControlDef.transitions:
                continue

            # part1=transition, part2=state, part3=config
            with self.daqState_cv:
                self.daqState = part2
                self.daqState_cv.notify()

    def _set_connected(self):
        self.push_socket.send_string('connected')
        # wait for complete
        self.ready.wait()
        self.ready.clear()

    def stage(self):
        # done once at start of scan
        # put the daq into the right state ('connected')
        """Put the DAQ in 'connected' (blocking until done) and reset the step count to 0."""
        self._set_connected()
        self._step_count = 0

    def unstage(self):
        # done once at end of scan
        # put the daq into the right state ('connected')
        """Log the step count and put the DAQ in 'connected', blocking until done."""
        logging.debug('*** unstage: step count = %d' % self._step_count)
        self._set_connected()

    # use 'motors' keyword arg to specify a set of motors
    def configure(self, *args, **kwargs):
        """Store the 'motors' keyword argument in `self.motors`.

        Logs an error if 'motors' is not given; positional arguments are ignored.
        """
        logging.debug("*** here in configure")

        if 'motors' in kwargs:
            self.motors = kwargs['motors']
            logging.info('configure: %d motors' % len(self.motors))
        else:
            logging.error('configure: no motors')

    def getMotors(self):
        """Return the list of motors set by `configure`."""
        return self.motors

    def step_count(self):
        """Return the number of steps triggered since the last `stage`."""
        return self._step_count

    def update(self, *, value):
        # update 'motors'
        """Call ``motor.update(value)`` on every motor in `self.motors`."""
        for motor in self.motors:
            motor.update(value)

    def trigger(self, *, phase1Info=None):
        # do one step
        """Request one scan step and increment the step count.

        Fills in missing 'beginstep', 'configure', ``configure['step_keys']`` and
        ``beginstep['step_values']`` entries of `phase1Info`, then pushes 'running,<json>' and
        'starting' to the communicator thread. Does not wait for the step to finish.

        Parameters
        ----------
        phase1Info : dict, optional
            Phase-1 info; modified in place when given.
        """
        logging.debug('*** trigger: step count = %d' % self._step_count)
        if phase1Info is None:
            phase1Info = {}
        if "beginstep" not in phase1Info:
            phase1Info.update({"beginstep": {}})
        if "configure" not in phase1Info:
            phase1Info.update({"configure": {}})
        if "step_keys" not in phase1Info["configure"]:
            phase1Info["configure"].update({"step_keys": []})
        if "step_values" not in phase1Info["beginstep"]:
            phase1Info["beginstep"].update({"step_values": {}})

        logging.debug('*** phase1Info = %s' % oldjson.dumps(phase1Info))
        # BeginStep
        self.push_socket.send_string('running,%s' % oldjson.dumps(phase1Info))
        # EndStep
        self.push_socket.send_string('starting')
        self._step_count += 1

#
# data = {
#   "motors":           {"motor1": 0.0, "step_value": 0.0},
#   "transition":       "Configure",
#   "timestamp":        0,
#   "add_names":        True,
#   "add_shapes_data":  False,
#   "detname":          "scan",
#   "dettype":          "scan",
#   "scantype":         "scan",
#   "serial_number":    "1234",
#   "alg_name":         "raw",
#   "alg_version":      [2,0,0]
# }
#

    def getBlock(self, *, transition, data):
        """Fill step-info fields in `data` and return ``control.getBlock(data)``.

        Sets 'transitionid' from `ControlDef.transitionId` (logs an error if `transition` is
        unknown), sets 'add_names'/'add_shapes_data' to True/False for 'Configure' and
        False/True otherwise, and sets 'namesid' to `ControlDef.STEPINFO`.

        Parameters
        ----------
        transition : str
            Transition name, e.g. 'Configure'.
        data : dict
            Block description; must contain 'motors'. Modified in place.

        Returns
        -------
        object
            Whatever `control.getBlock` returns.
        """
        logging.debug('getBlock: motors=%s' % data["motors"])
        if transition in ControlDef.transitionId.keys():
            data["transitionid"] = ControlDef.transitionId[transition]
        else:
            logging.error(f'invalid transition: {transition}')

        if transition == "Configure":
            data["add_names"] = True
            data["add_shapes_data"] = False
        else:
            data["add_names"] = False
            data["add_shapes_data"] = True

        data["namesid"] = ControlDef.STEPINFO

        return self.control.getBlock(data)
