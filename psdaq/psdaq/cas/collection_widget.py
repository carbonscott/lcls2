"""PyQt5 widget that sends collection requests (rollcall/alloc/connect, reset, getstate) over ZMQ and lists the processes."""
import sys
import zmq
from datetime import datetime, timezone
from PyQt5 import QtCore, QtGui, QtWidgets

PORT_BASE = 29980
POSIX_TIME_AT_EPICS_EPOCH = 631152000

def timestampStr():
    """Return the current UTC time as ``'%010d-%09d' % (sec, nsec)`` with seconds since the EPICS epoch."""
    current = datetime.now(timezone.utc)
    nsec = 1000 * current.microsecond
    sec = int(current.timestamp()) - POSIX_TIME_AT_EPICS_EPOCH
    return '%010d-%09d' % (sec, nsec)


def create_msg(key, msg_id=None, sender_id=None, body={}):
    """Build a ``{'header': {...}, 'body': body}`` message with key `key`.

    The dict is only built when `msg_id` is None (a timestamp is then used); passing a
    `msg_id` leaves `msg` unassigned and raises UnboundLocalError.
    """
    if msg_id is None:
        msg_id = timestampStr()
        msg = {'header': {
               'key': key,
               'msg_id': msg_id,
               'sender_id': sender_id},
           'body': body}
    return msg

def rep_port(platform):
    """Return ``PORT_BASE + platform + 20`` (PORT_BASE is 29980)."""
    return PORT_BASE + platform + 20


class CollectionWidget(QtWidgets.QWidget):
    """Widget with 'Auto connect' and 'Reset' buttons and drp/teb/meb host lists.

    A ZMQ REQ socket is connected to 'tcp://drp-tst-acc06:<rep_port(partition)>'.
    """
    def __init__(self, partition, parent=None):
        super().__init__(parent)
        self.context = zmq.Context(1)
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect('tcp://drp-tst-acc06:%d' %rep_port(partition))

        layout = QtWidgets.QGridLayout()
        layout.addWidget(QtWidgets.QLabel('Collection') , 0, 0, 1, 3)

        l = QtWidgets.QHBoxLayout()
        button = QtWidgets.QPushButton('Auto connect')
        button.clicked.connect(self.auto_connect)
        l.addWidget(button)

        button = QtWidgets.QPushButton('Reset')
        button.clicked.connect(self.reset)
        l.addWidget(button)
        layout.addLayout(l, 1, 0, 1, 3)

        self.label = QtWidgets.QLabel()
        layout.addWidget(self.label, 2, 0, 1, 3)

        self.listWidgets = {}
        for i, group in enumerate(['drp', 'teb', 'meb']):
            layout.addWidget(QtWidgets.QLabel(group), 3, i)
            w = QtWidgets.QListWidget()
            layout.addWidget(w, 4, i)
            self.listWidgets[group] = w
        self.setLayout(layout)
        self.setMaximumWidth(300)

    def auto_connect(self):
        """Send 'rollcall', 'alloc' and 'connect' requests in turn, then refresh the lists with `get_state`.

        Each reply is printed; if one has ``body['err_info']`` it is shown in the label and the sequence stops.
        """
        self.label.clear()
        for w in self.listWidgets.values():
            w.clear()
        for cmd in ['rollcall', 'alloc', 'connect']:
            self.socket.send_json(create_msg(cmd))
            response = self.socket.recv_json()
            print(response)
            if 'err_info' in response['body']:
                self.label.setText(response['body']['err_info'])
                return
        self.get_state()


    def reset(self):
        """Clear the label and lists, send a 'reset' request and print the reply."""
        self.label.clear()
        for w in self.listWidgets.values():
            w.clear()
        self.socket.send_json(create_msg('reset'))
        print(self.socket.recv_json())


    def get_state(self):
        """Send 'getstate' and fill the drp/teb/meb lists with each entry's ``proc_info['host']``; unknown groups are printed."""
        msg = create_msg('getstate')
        self.socket.send_json(msg)
        reply = self.socket.recv_json()
        for group in reply['body']:
            if group not in self.listWidgets:
                print('unknown group:', group)
                continue
            w = self.listWidgets[group]
            w.clear()
            for k, v in reply['body'][group].items():
                host = v['proc_info']['host']
                QtWidgets.QListWidgetItem(host, w)

if __name__ == '__main__':
    app = QtWidgets.QApplication([])                      
    widget = CollectionWidget()
    widget.show()
    sys.exit(app.exec_())
