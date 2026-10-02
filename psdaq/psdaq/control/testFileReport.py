#!/usr/bin/env python

"""
Test File Report
"""

from datetime import datetime, timezone
import zmq
from psdaq.control.control import back_pull_port, create_msg
import argparse

def fileReport_msg(path):
    """Return a 'fileReport' message for `path`.

    The body holds 'path', 'create_timestamp' and 'modify_timestamp' (both the current UTC
    time formatted as ``%Y-%m-%dT%H:%M:%SZ``) and 'size' set to 0.

    Parameters
    ----------
    path : str
        File name to report.

    Returns
    -------
    dict
        Message built by `create_msg`.
    """
    dt = datetime.now(timezone.utc)
    dts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {'path': path,
            'create_timestamp': dts,
            'modify_timestamp': dts,
            'size':0}
    return create_msg('fileReport', body=body)

class Client:
    """Send one fileReport message to the collection host.

    The constructor connects a PUSH socket to `back_pull_port(platform)` on `collectHost`
    and sends ``fileReport_msg(path)`` as JSON.
    """
    def __init__(self, platform, collectHost, path):

        # configure zmq sockets
        self.context = zmq.Context(1)
        self.push = self.context.socket(zmq.PUSH)
        self.push.connect('tcp://%s:%d' % (collectHost, back_pull_port(platform)))

        # send fileReport message
        self.push.send_json(fileReport_msg(path))

def main():

    """Parse -p (platform), -C (collection host) and -P (path, required) and create a `Client`.

    KeyboardInterrupt is caught and printed.
    """
    try:
        # process arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-p', type=int, choices=range(0, 8), default=0, help='platform (default 0)')
        parser.add_argument('-C', metavar='COLLECT_HOST', default='localhost', help='collection host (default localhost)')
        parser.add_argument('-P', metavar='PATH', required=True, help='filename to report')
        args = parser.parse_args()

        # start client
        client = Client(args.p, args.C, args.P)

    except KeyboardInterrupt:
        print('KeyboardInterrupt')

if __name__ == '__main__':
    main()
