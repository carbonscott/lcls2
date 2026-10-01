
"""Small pyzmq socket wrappers that send and receive pickled Python objects, and `zmq_send`."""
import zmq

client_socket = None

def zmq_send(**kwargs):
    """Send the keyword arguments, except `fake_dbase_server`, as one dict.

    On the first call a module-level PUSH `SubSocket` is connected to the address given by
    `fake_dbase_server` and reused afterwards (later addresses are ignored). The dict is sent with
    `send_pyobj` and then printed.
    """
    global client_socket
    if client_socket is None:
        client_socket = SubSocket(kwargs["fake_dbase_server"], socket_type=zmq.PUSH)
    data = {}
    for key, val in kwargs.items():
        if key == "fake_dbase_server":
            continue
        data[key] = val
    client_socket.send(data)
    print(f"sent {data} to {kwargs['fake_dbase_server']}")


class ZMQSocket:
    """Wrap a zmq socket and exchange pickled Python objects (`send_pyobj` / `recv_pyobj`)."""
    def __init__(self, zmq_socket):
        self.socket = zmq_socket

    def send(self, data):
        """Send `data` as a pickled Python object with `socket.send_pyobj`."""
        self.socket.send_pyobj(data)

    def recv(self):
        """Receive one message with `socket.recv_pyobj` (blocking) and return the unpickled object."""
        return self.socket.recv_pyobj()


class PubSocket(ZMQSocket):
    """A helper for a Binder Zmq-Socket"""

    def __init__(self, socket_name, socket_type=zmq.PUB):
        context = zmq.Context()
        zmq_socket = context.socket(socket_type)
        zmq_socket.bind(socket_name)
        super(PubSocket, self).__init__(zmq_socket)


class SubSocket(ZMQSocket):
    """A helper for a Connector Zmq-Socket"""

    def __init__(self, socket_name, socket_type=zmq.SUB):
        context = zmq.Context()
        zmq_socket = context.socket(socket_type)
        zmq_socket.connect(socket_name)
        super(SubSocket, self).__init__(zmq_socket)

        # Subscribe to all
        if socket_type == zmq.SUB:
            topicfilter = ""
            self.socket.setsockopt_string(zmq.SUBSCRIBE, topicfilter)


class SrvSocket(ZMQSocket):
    """ZMQ REP socket bound to `socket_name`, created on a new `zmq.Context`."""
    def __init__(self, socket_name):
        context = zmq.Context()
        zmq_socket = context.socket(zmq.REP)
        zmq_socket.bind(socket_name)
        super(SrvSocket, self).__init__(zmq_socket)


class ClientSocket(ZMQSocket):
    """ZMQ REQ socket connected to `socket_name`, created on a new `zmq.Context`."""
    def __init__(self, socket_name):
        context = zmq.Context()
        zmq_socket = context.socket(zmq.REQ)
        zmq_socket.connect(socket_name)
        super(ClientSocket, self).__init__(zmq_socket)
