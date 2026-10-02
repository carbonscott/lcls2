"""ZeroMQ PUB/SUB plus REQ/REP barrier for DRP processes sharing a host, and a helper to pick the supervisor."""
import zmq
import time
import os
import socket

def supervisor_info(json_msg,mydev):
    """Find this process's role among the active DRPs on this host in a connect message.

    DRPs count when their host is this host, they are active and, on hosts whose name contains
    'gpu', their 'device' equals `mydev`.

    Returns
    -------
    tuple
        ``(supervisor, nworker)``: `supervisor` is True if the first counted entry has this
        process's pid, False if not, None if no entry counted; `nworker` is the number of counted
        entries after the first.
    """
    nworker = 0
    supervisor=None
    mypid = os.getpid()
    myhostname = socket.gethostname()
    for drp in json_msg['body']['drp'].values():
        proc_info = drp['proc_info']
        host = proc_info['host']
        pid = proc_info['pid']
        dev = proc_info['device']
        #  Check for the same FPGA board (assume non-gpu hosts have only one board)
        same_board = ('gpu' not in myhostname) or (dev==mydev)
        if host==myhostname and same_board and drp['active']:
            if supervisor is None:
                # we are supervisor if our pid is the first entry
                supervisor = pid==mypid
            else:
                # only count workers for second and subsequent entries on this host
                nworker+=1
    return supervisor,nworker
            

class Barrier:
    """
    From https://zguide.zeromq.org/docs/chapter2/#Node-Coordination
    """
    def __init__(self):
        self.context = zmq.Context()
        self.nworker = 0
        self.publisher = False
        self.subscriber = False
        self.supervisor = False

    def __del__(self):
        self.shutdown()

    def init(self, supervisor, nworker, port1=5561, port2=5562):
        """Store the role and ports and, unless `nworker` is 0, run `supervisor_init` or `worker_init`.

        Parameters
        ----------
        supervisor : bool
            True for the supervisor process.
        nworker : int
            Number of workers; 0 makes every barrier call a no-op.
        port1 : int, optional
            PUB/SUB port. Default 5561.
        port2 : int, optional
            REQ/REP port. Default 5562.
        """
        self.supervisor = supervisor
        self.nworker = nworker
        self.port1 = port1
        self.port2 = port2
        if self.nworker==0: return # do nothing if only one opal
        if self.supervisor:
            self.supervisor_init()
        else:
            self.worker_init()

    def shutdown(self):
        # To be called on the deallocate transition
        """Close this process's sockets and reset `nworker` to 0; does nothing if `nworker` is already 0.

        The code comment says it is to be called on the deallocate transition.
        """
        if self.nworker==0: return
        if self.supervisor:
            self.publisher.close()
            self.syncservice.close()
        else:
            self.subscriber.close()
            self.syncworker.close()
        self.nworker = 0
        self.publisher = False
        self.subscriber = False

    def supervisor_init(self):
        # Socket to talk to workers
        """Bind the PUB socket on `port1` and REP socket on `port2` (first time only), then answer one empty request from each of `nworker` workers.

        Blocks until all workers have sent their request.
        """
        if not self.publisher:
            self.publisher = self.context.socket(zmq.PUB)
            # set SNDHWM, so we don't drop messages for slow subscribers
            # cpo: not necessary for this example since we're sending slow/small msgs
            #self.publisher.sndhwm = 1100000
            self.publisher.bind(f"tcp://*:{self.port1}")
            # Socket to receive signals
            self.syncservice = self.context.socket(zmq.REP)
            self.syncservice.bind(f"tcp://*:{self.port2}")

        # Get synchronization from subscribers
        subscribers = 0
        while subscribers < self.nworker:
            # wait for synchronization request
            msg = self.syncservice.recv()
            # send synchronization reply
            self.syncservice.send(b'')
            subscribers += 1

    def worker_init(self):
        """Connect SUB to localhost `port1` and REQ to localhost `port2` (first time only, with a 1 s sleep between), then send an empty request and wait for the reply."""
        if not self.subscriber:
            self.subscriber = self.context.socket(zmq.SUB)
            self.subscriber.connect(f"tcp://localhost:{self.port1}")
            self.subscriber.setsockopt(zmq.SUBSCRIBE, b'')

            """
            From https://zguide.zeromq.org/docs/chapter2/#Node-Coordination
            We can’t assume that the SUB connect will be finished
            by the time the REQ/REP dialog is complete. There are
            no guarantees that outbound connects will finish in any
            order whatsoever, if you’re using any transport except
            inproc. So, the example does a brute force sleep of one
            second between subscribing, and sending the REQ/REP synchronization.
            """
            time.sleep(1)

            # Second, synchronize with publisher
            self.syncworker = self.context.socket(zmq.REQ)
            self.syncworker.connect(f"tcp://localhost:{self.port2}")

        # send a synchronization request
        self.syncworker.send(b'')

        # wait for synchronization reply
        self.syncworker.recv()

    def wait(self):
        """Supervisor: publish b'unblock'. Worker: block until a message arrives on the SUB socket.

        Does nothing if `nworker` is 0.
        """
        if self.nworker==0: return # do nothing if only one opal
        if self.supervisor:
            self.publisher.send(b"unblock")
        else:
            self.subscriber.recv()

if __name__ == "__main__":

    import sys
    import time
    supervisor = sys.argv[1]=='s'
    nworker = int(sys.argv[2])
    port1 = 5561
    port2 = 5562

    barrier = Barrier()
    barrier.init(supervisor,nworker,port1,port2)
    for i in range(5):
        if supervisor: time.sleep(1) # supervisor does some work
        barrier.wait() # allow workers to continue
        print('done',supervisor)
