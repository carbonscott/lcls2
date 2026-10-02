#!/usr/bin/env python

"""
Asynchronous Error Test
"""

import time
import socket
import zmq
from psdaq.control.control import back_pull_port, error_msg, warning_msg
import argparse

class Client:
    """Send error and/or warning messages to the collection host.

    The constructor connects a PUSH socket to ``back_pull_port(args.p)`` on host ``args.C``
    and sends `error_msg` and/or `warning_msg` with text ``'<alias>: <message>'`` for
    whichever of ``args.error``/``args.warning`` is not None.
    """
    def __init__(self, args):

        # configure zmq sockets
        self.context = zmq.Context(1)
        self.push = self.context.socket(zmq.PUSH)
        self.push.connect('tcp://%s:%d' % (args.C, back_pull_port(args.p)))

        if args.error is not None:
            # send error message
            self.push.send_json(error_msg("%s: %s" % (args.alias, args.error)))

        if args.warning is not None:
            # send warning message
            self.push.send_json(warning_msg("%s: %s" % (args.alias, args.warning)))

def main():

    """Parse command-line arguments and create a `Client`.

    Options: -p platform, -C collection host, --error, --warning, --alias (required). It is
    a parser error if neither --error nor --warning is given. KeyboardInterrupt is caught and printed.
    """
    try:
        # process arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-p', type=int, choices=range(0, 8), default=0, help='platform (default 0)')
        parser.add_argument('-C', metavar='COLLECT_HOST', default='localhost', help='collection host (default localhost)')
        parser.add_argument('--error', metavar='ERR_MSG')
        parser.add_argument('--warning', metavar='WARN_MSG')
        parser.add_argument('--alias', metavar='ALIAS', required=True)
        args = parser.parse_args()

        if args.error is None and args.warning is None:
            parser.error('Must specify --error or --warning or both')

        # start client
        client = Client(args)

    except KeyboardInterrupt:
        print('KeyboardInterrupt')

if __name__ == '__main__':
    main()
