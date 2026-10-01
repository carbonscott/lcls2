"""Define `PacketFooter`, which reads and writes the size footer at the end of a buffer of concatenated packets."""
import struct

import numpy as np


class PacketFooter(object):

    """Footer of packet sizes stored at the end of a buffer.

    The footer holds one 4-byte unsigned int (struct format "I", native byte order) per packet with
    that packet's size, followed by the number of packets. Pass `n_packets` to create an empty
    footer for that many packets, `view` to read the footer at the end of an existing buffer, or
    neither for an empty footer with no packets.
    """
    n_bytes = 4

    def __init__(self, n_packets=0, view=None):
        """Creates footer for packets
        footer format = | size of packet 0 | size of packet 1 | ... size of packet N | n_packets
        Each footer element has n_bytes.
        If n_packets is given, creates an empty footer with n_packets .
        If footer is given, sets footer that's available for packet size access.
        """

        if n_packets:
            self.n_packets = n_packets
            self.footer = bytearray((n_packets + 1) * self.n_bytes)
            self.footer[-self.n_bytes :] = struct.pack("I", self.n_packets)
        elif view:
            self.n_packets = struct.unpack("I", view[-self.n_bytes :])[0]
            self.footer = view[-(self.n_packets + 1) * self.n_bytes :]
            self.view = view
        else:
            self.n_packets = 0
            self.footer = bytearray()

    def set_size(self, idx, size):
        """Set size of the given packet index."""
        assert idx < self.n_packets
        st = idx * self.n_bytes
        self.footer[st : st + self.n_bytes] = struct.pack("I", size)

    def get_size(self, idx):
        """Return size of the given packet index."""
        assert idx < self.n_packets
        st = idx * self.n_bytes
        return struct.unpack("I", self.footer[st : st + self.n_bytes])[0]

    def split_packets(self):
        """Return list of memoryviews to packets"""
        # generate list of offsets and sizes for the packets
        sizes = np.asarray([self.get_size(idx) for idx in range(self.n_packets)])
        offsets = np.asarray([np.sum(sizes[:idx]) for idx in range(self.n_packets)])

        memviews = [
            memoryview(self.view[offsets[idx] : offsets[idx] + sizes[idx]])
            for idx in range(self.n_packets)
        ]
        return memviews

    def add_packet(self, packet_size):
        """Appends the packet_size to the footer and upates n_packets."""
        self.n_packets += 1
        self.footer[-self.n_bytes : -self.n_bytes] = bytearray(
            struct.pack("I", packet_size)
        )
        self.footer[-self.n_bytes :] = struct.pack("I", self.n_packets)
