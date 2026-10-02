"""Python side of the TEB trigger: exchanges messages over POSIX message queues and reads/writes event data in POSIX shared memory.

The queues are '/mqtebinp_<key>' (inputs) and '/mqtebres_<key>' (results), with
<key> taken from the -b argument without its first character.
"""
import sys
import numpy
import posix_ipc
import mmap
import logging
import json
import argparse

from struct import unpack
import psdaq.EbDgram     as edg
import psdaq.ResultDgram as rdg
import psdaq.CubeConfigDgram as cdg
import psdaq.CubeResultDgram as qdg
import psdaq.WindowResultDgram as wdg

class ArgsParser(argparse.ArgumentParser):
    """Argument parser with -p (partition 0-7, default 0) and -b (IPC key base, required)."""
    def __init__(self):
        super(ArgsParser, self).__init__()
        self.add_argument('-p', type=int, choices=range(0, 8), default=0, help='partition (default 0)')
        self.add_argument('-b', type=str, required=True, help='IPC key base value')

    def parse(self):
        """Parse the command line, store the namespace in `self.args` and return it."""
        self.args = self.parse_args()
        return self.args

class TriggerDataSource(object):
    """Connect to the TEB message queues and shared memory and receive the connect info.

    The constructor parses arguments, opens both queues (exits with status 1 on error),
    maps the 'i' (inputs) and 'r' (results) shared memory announced by the TEB (replying
    'g'), accumulates the connect JSON from 'c'/'d' messages into `connect_json`/
    `connect_info`, then waits for 'g' (calling `cfg_cb` if given, else replying 'g') or 's'.
    """
    def __init__(self, cfg_cb=None):

        logging.info(f"[Python] Starting")

        self._cfg_cb = cfg_cb
        self._mq_inp = None
        self._mq_res = None
        self._shm_inp = None
        self._shm_res = None

        self.connect_json = None
        self.connect_info = None
        self._det_src = dict()

        # Make args available to the user scripts
        self.args = ArgsParser().parse()

        # Make the base key value depend on the partition number
        key_base = self.args.b[1:]

        try:
            self._mq_inp = posix_ipc.MessageQueue("/mqtebinp_" + key_base, read=True, write=False)
        except posix_ipc.Error as exp:
            print(
                f"[Python] Error connecting to 'Inputs' message queue - Error: {exp}"
            )
            sys.exit(1)

        try:
            self._mq_res = posix_ipc.MessageQueue("/mqtebres_" + key_base, read=False, write=True)
        except posix_ipc.Error as exp:
            print(
                f"[Python] Error connecting to 'Results' message queue - Error: {exp}"
            )
            sys.exit(1)

        print(f"[Python] Connected to message queues")

        while True: # Synch up when there's cruft in the pipe
            message, priority = self._mq_inp.receive()
            print(f"[Python] Received message '{message}', prio '{priority}'")

            if chr(message[0]) != 'i':
                print(f"[Python] Unrecognized message '{chr(message[0])}'; expected 'i'")
            else:
                try:
                    shm_msg = message.decode().split(',')
                    self._shm_inp = posix_ipc.SharedMemory(shm_msg[1], size=int(shm_msg[2]))
                    inputsSize = 0
                    self._shm_inp_bufSizes = []
                    for ctrbSize in shm_msg[3:]:
                        self._shm_inp_bufSizes.append(inputsSize)
                        inputsSize += int(ctrbSize)
                    self._shm_inp_bufSizes.append(inputsSize)
                    self._shm_inp_mmap = mmap.mmap(self._shm_inp.fd, self._shm_inp.size)

                except posix_ipc.Error as exp:
                    print(
                        f"[Python] Error connecting to 'Inputs' shared memory - Error: {exp}"
                    )
                    sys.exit(1)

                print(f"[Python] Set up Inputs shared memory key {shm_msg[1]} size {shm_msg[2]}")
                break

        self._mq_res.send(b"g")

        while True: # Synch up when there's cruft in the pipe
            message, priority = self._mq_inp.receive()
            print(f"[Python] Received message '{message}', prio '{priority}'")

            if chr(message[0]) != 'r':
                print(f"[Python] Unrecognized message '{chr(message[0])}'; expected 'r'")
            else:
                try:
                    shm_msg = message.decode().split(',')
                    self._shm_res = posix_ipc.SharedMemory(shm_msg[1], size=int(shm_msg[2]))
                    self._shm_res_mmap = mmap.mmap(self._shm_res.fd, self._shm_res.size)
                except posix_ipc.Error as exp:
                    print(
                        f"[Python] Error connecting to 'Results' shared memory - Error: {exp}"
                    )
                    self._shm_inp.unlink()
                    self._shm_inp = None
                    sys.exit(1)

                print(f"[Python] Set up Results shared memory key {shm_msg[1]} size {shm_msg[2]}")
                break

        #print(f'max_size: {self._mq_inp.max_size}')

        connectMsg = ''
        while True:
            message, priority = self._mq_inp.receive()
            print(f"[Python] Received message '{message[:10]}', len '{len(message)}, prio '{priority}'")

            if   chr(message[0]) in ('c', 'd'):
                size        = int((message.decode())[2:])
                connectMsg += self._shm_inp_mmap[0:size].decode()
                if chr(message[0]) == 'd':
                    print(f"[Python] Received connect message '{connectMsg[:40]}...'")
                    self.connect_json = connectMsg
                    self.connect_info = json.loads(connectMsg)
                    break

            else:
                print(f"[Python] Unrecognized message '{chr(message[0])}'; expected 'c' or 'd'")
                continue

            self._mq_res.send(b"c")

        self._mq_res.send(b"d") # Done

        #  Now, wait for Configure
        while True:
            message, priority = self._mq_inp.receive()
            #print(f"[Python] Received msg '{message}', prio '{priority}'")

            if chr(message[0]) == 'g':
                if self._cfg_cb:
                    self._cfg_cb()
                else:
                    self._mq_res.send(b"g")
                break
            elif chr(message[0]) == 's':  # this might be problematic
                print(f"[Python] Received stop while waiting for Configure")
                break
            else:
                print(f"[Python] Unrecognized message '{chr(message[0])}' received")


    def __del__(self):
        if self._shm_inp is not None:
            self._shm_inp.unlink()
            self._shm_inp = None
        if self._shm_res is not None:
            self._shm_res.unlink()
            self._shm_res = None

    def events(self):
        """Generator yielding an `Event` for each 'g' message (contributor mask from the hex digits after 'g'); stops on 's'."""
        print("[Python] TriggerDataSource.events() called")

        while True:
            message, priority = self._mq_inp.receive()
            #print(f"[Python] Received msg '{message}', prio '{priority}'")

            if chr(message[0]) == 'g':
                event = Event(self._shm_inp_mmap, self._shm_inp_bufSizes, int(message[1:],16), self._det_src)
                yield event
            elif chr(message[0]) == 's':
                break
            else:
                print(f"[Python] Unrecognized message '{chr(message[0])}' received")

    def result(self, persist, monitor):

        """Write a `ResultDgram(persist, monitor)` into the results shared memory and send 'g'."""
        result = rdg.ResultDgram(self._shm_res_mmap, persist, monitor)
        self._mq_res.send(b"g")

        #print(
        #    f"[Python] Sent message 'g'"
        #)

    def mebs(self, names=None):
        """Return a bitmask of 'meb_id' bits from the connect info's 'meb' entries.

        With `names` None every MEB is included; a str or list selects MEBs whose alias
        contains it (or any of them). Returns 0 if there is no 'meb' section.
        """
        r = 0
        if 'meb' in self.connect_info['body'].keys():
            for nodes in self.connect_info['body']['meb'].values():
                if names is None:
                    r |= 1 << nodes['meb_id']
                elif isinstance(names,str):
                    if names in nodes['proc_info']['alias']:
                        r |= 1 << nodes['meb_id']
                elif isinstance(names,list):
                    for n in names:
                         if n in nodes['proc_info']['alias']:
                             r |= 1 << nodes['meb_id']
                    
        return r

    def detector(self, name, tebType):
        """Register the drp named `name` (exact alias match) and return a `Detector(index, tebType)` for it.

        Raises
        ------
        RuntimeError
            If no drp has that alias.
        """
        index = -1
        for nodes in self.connect_info['body']['drp'].values():
            if name == nodes['proc_info']['alias']:
                index = len(self._det_src)
                self._det_src[nodes['drp_id']] = index
                break

        if index<0:
            raise RuntimeError(f'Detector {name} not found')

        return Detector(index, tebType)

class CubeTriggerDataSource(TriggerDataSource):

    """`TriggerDataSource` whose configure step writes a 'Cube' `CubeConfigDgram` built from `config` (uses ``config['bins']``)."""
    def __init__(self, config):
        self.config = config
        TriggerDataSource.__init__(self, self.configure)


    def configure(self):
        """Write a `CubeConfigDgram` with ``config['bins']`` bins, name 'Cube' and the JSON config into the results memory, then send 'g'."""
        nbins = self.config['bins']
        logging.warning(f'[Python] Setting nbins {nbins}')
        result = cdg.CubeConfigDgram(self._shm_res_mmap, nbins, 'Cube', json.dumps(self.config))

        self._mq_res.send(b"g")

    """  persist     : put event into the cube
         record      : record event 
         monitor     : forward event to monitoring
         bin_index   : cube bin the event sums into
         bin_record  : record the cube bin 
         bin_monitor : forward the cube bin to monitoring
         flush       : reset the cube after this event is processed
    """
    def result(self, persist, record, monitor, bin_index, bin_record, bin_monitor, flush=False):
        """Write a `CubeResultDgram` with the given flags and bin index into the results memory and send 'g'.

        The string above this method in the class body describes the arguments.
        """
        result = qdg.CubeResultDgram(self._shm_res_mmap, persist, record, monitor, 
                                     bin_index, bin_record, bin_monitor, flush)
        self._mq_res.send(b"g")

class WindowTriggerDataSource(TriggerDataSource):

    """`TriggerDataSource` whose configure step writes a 'Window' `CubeConfigDgram` built from `config` (uses ``config['bins']``)."""
    def __init__(self, config):
        self.config = config
        TriggerDataSource.__init__(self, self.configure)


    def configure(self):
        """Write a `CubeConfigDgram` with ``config['bins']`` bins, name 'Window' and the JSON config into the results memory, then send 'g'."""
        nbins = self.config['bins']
        logging.warning(f'[Python] Setting nbins {nbins}')
        result = cdg.CubeConfigDgram(self._shm_res_mmap, nbins, 'Window', json.dumps(self.config))

        self._mq_res.send(b"g")

    """  persist     : keep the event (push into the cube)
         monitor     : where to forward the event for monitoring
         win_add     : list of windows to add event into
         win_record  : list of windows to record
         win_monitor : list of windows to monitor
         win_flush   : list of windows to reset after this event is processed
    """
    def result(self, persist, monitor, win_add, win_record, win_monitor, win_flush):
        """Write a `WindowResultDgram` with the given flags and window lists into the results memory and send 'g'.

        The string above this method in the class body describes the arguments.
        """
        result = wdg.WindowResultDgram(self._shm_res_mmap, persist, monitor, 
                                        win_add, win_record, win_monitor, win_flush)
        self._mq_res.send(b"g")

# Revisit: Move this into a .pyx?
class Event(object):
    """One event's contributions in the inputs shared memory; iterating yields an `EbDgram` per contributor bit set in `ctrb`.

    Iteration stops early (with a printed message) on a pulse-ID mismatch.
    """
    def __init__(self, shm_inp_mmap, shm_bufSizes, ctrb, det_src):
        self._shm_inp_mmap      = shm_inp_mmap
        self._shm_bufSizes = shm_bufSizes
        self._ctrb = ctrb
        self._idx = 0
        self._pid = None
        self._det_src = det_src
        self._det_lookup = None
        self._readout_groups = None

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            if self._idx == len(self._shm_bufSizes):
                raise StopIteration
            if (self._ctrb >> self._idx)&1:
                break
            self._idx += 1

        beg = self._shm_bufSizes[self._idx]
        end = self._shm_bufSizes[self._idx + 1]
        datagram = edg.EbDgram(view=self._shm_inp_mmap[beg:end])
        self._readout_groups = datagram.readoutGroups()

        self._idx += 1

        # Consistency check to make sure we haven't run off the end
        if self._pid is None:
            self._pid = datagram.pulseId()
        elif datagram.pulseId() != self._pid:
            print(f"[Python] PulseId mismatch: "
                  f"expected {'%014x'%self._pid}, "
                  f"got {'%014x'%datagram.pulseId()}, src {datagram.xtc.src.value():x}")
            raise StopIteration

        return datagram

    def payload(self):
        """Return (and cache) {detector index: xtc payload} for contributors registered with `TriggerDataSource.detector`."""
        if self._det_lookup is None:
            #            self._det_lookup = get_teb_lookup(self)
            self._det_lookup = dict()
            for i in range( len(self._shm_bufSizes) ):
                if (self._ctrb >> i)&1:
                    beg = self._shm_bufSizes[i]
                    end = self._shm_bufSizes[i + 1]
                    datagram = edg.EbDgram(view=self._shm_inp_mmap[beg:end])
                    self._readout_groups = datagram.readoutGroups()
                    src = datagram.xtc.src.value()
                    if src in self._det_src:
                        self._det_lookup[ self._det_src[src] ] = datagram.xtc.payload()
        return self._det_lookup

    def readoutGroups(self):
        """Return the readout groups of the first contributing datagram (cached)."""
        if self._readout_groups is None:
            for i in range( len(self._shm_bufSizes) ):
                if (self._ctrb >> i)&1:
                    beg = self._shm_bufSizes[i]
                    end = self._shm_bufSizes[i + 1]
                    datagram = edg.EbDgram(view=self._shm_inp_mmap[beg:end])
                    self._readout_groups = datagram.readoutGroups()
                    break
        return self._readout_groups

class Detector(object):
    """Handle for a registered drp: converts its payload with `tebType`."""
    def __init__(self, index, tebType):
        self._tebId   = index
        self._tebType = tebType

    def trigger(self, event):
        """Return ``tebType(payload)`` for this detector in `event`, or None if the payload is empty.

        Raises KeyError if the detector did not contribute to the event.
        """
        payld = event.payload()[self._tebId]
        return self._tebType(payld) if payld else None
