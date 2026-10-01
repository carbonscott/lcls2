######################################################################################
# Simple Database for storing psplot process detail created by psplot server.
# Instance:
#    PK
#   {1: slurm_job_id1, rixc00221, 49, sdfmilan032, 12301, pid, DbHistoryStatus.PLOTTED,
#    2: slurm_job_id2, rixc00221, 50, sdfmilan032, 12301, pid, DbHistoryStatus.PLOTTED,
#    3: slurm_job_id3, rixc00221, 49, sdfmilan032, 12301, pid, DbHistoryStatus.RECEIVED,
#
# The server runs on zmq and has two ways of getting db info:
#   1. Client sends info directly via zmq socket
#   2. Client is a kafka producer. The server initiates kafka consumer asyncio process
#      that listens to the producers. The asyncio process takes care of sending info
#      to zmq socket.
######################################################################################

"""In-memory store of psplot process records for the psplot_live server, with a zmq REP socket for client requests."""
import socket
from psana.psexp.zmq_utils import SrvSocket


class DbHistoryStatus:
    """Record status codes: RECEIVED=0, PLOTTED=1."""
    RECEIVED = 0
    PLOTTED = 1

    @staticmethod
    def get_name(ID):
        """Return "RECEIVED" for 0 or "PLOTTED" for 1; any other value raises KeyError."""
        info = {0: "RECEIVED", 1: "PLOTTED"}
        return info[ID]


class DbHistoryColumns:
    """Column indexes of a record: SLURM_JOB_ID=0, EXP=1, RUNNUM=2, NODE=3, PORT=4, PID=5, STATUS=6."""
    SLURM_JOB_ID = 0
    EXP = 1
    RUNNUM = 2
    NODE = 3
    PORT = 4
    PID = 5
    STATUS = 6


class DbConnectionType:
    """Connection type codes: ZMQ=0, KAFKA=1."""
    ZMQ = 0
    KAFKA = 1


class DbHelper:
    """In-memory table of records (`instance`: id -> list of column values) plus a zmq REP server socket for requests."""
    def __init__(self):
        self.instance = {}

    def connect(self, socket_name):
        """Bind a zmq REP socket (`SrvSocket`) to `socket_name` and keep it as `srv_socket`."""
        self.srv_socket = SrvSocket(socket_name)

    @staticmethod
    def get_socket(port=None):
        # We acquire an available port using a socket then closing it immediately
        # so that this port can be used later.
        """Return the address `tcp://<host IP>:<port>` for this host.

        If `port` is None, a free port is found by binding a temporary socket to port 0 and closing it.
        """
        IPAddr = socket.gethostbyname(socket.gethostname())
        if port is None:
            sock = socket.socket()
            sock.bind(("", 0))
            port = sock.getsockname()[1]
            sock.close()
        supervisor_ip_addr = f"{IPAddr}:{port}"
        socket_name = f"tcp://{supervisor_ip_addr}"
        return socket_name

    def recv(self):
        """Print "Waiting for client...", then block until a request arrives on `srv_socket` and return the unpickled object."""
        print("Waiting for client...")
        info = self.srv_socket.recv()
        return info

    def send(self, data, include_instance=False):
        """Send `data` (pickled) on `srv_socket`; with `include_instance` the whole record table is first added as `data["instance"]`."""
        if include_instance:
            data["instance"] = self.instance
        self.srv_socket.send(data)

    def set(self, instance_id, what, val):
        """Set column `what` of record `instance_id` to `val`."""
        self.instance[instance_id][what] = val

    def save(self, obj):
        """Add a record built from `obj` and return its id.

        The record holds `obj`'s slurm_job_id, exp, runnum, node and port, pid None and status RECEIVED;
        the id is 1 for an empty table, otherwise the largest id plus 1.
        """
        next_id = 1
        if self.instance:
            ids = list(self.instance.keys())
            next_id = max(ids) + 1
        self.instance[next_id] = [
            obj["slurm_job_id"],
            obj["exp"],
            obj["runnum"],
            obj["node"],
            obj["port"],
            None,
            DbHistoryStatus.RECEIVED,
        ]
        return next_id

    def get(self, instance_id):
        """Return the record for `instance_id`, or None if there is none."""
        found_instance = None
        if instance_id in self.instance:
            found_instance = self.instance[instance_id]
        return found_instance

    def delete(self, instance_id):
        """Remove record `instance_id` if present and print the removed value ("No Key found" if it was missing); returns None."""
        removed_value = self.instance.pop(instance_id, "No Key found")
        print(f"delete called {removed_value=}")
