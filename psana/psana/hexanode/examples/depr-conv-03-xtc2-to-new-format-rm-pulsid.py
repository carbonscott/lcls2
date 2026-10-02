"""Script: copy datagrams from file ``sys.argv[1]`` to file ``sys.argv[2]``, dropping the first two 32-bit header words of each.

Each datagram is read with ``OldDgram`` and written with ``writeNoPulseId``. The loop ends at the first exception (expected at end of file), prints 'done' and closes both files.
"""
import numpy as np
import sys

class OldDgram:
    """Datagram read from an open file: an 8-word uint32 header followed by ``extent - 12`` payload bytes, where extent is header word 7."""
    def __init__(self,f):
        headerwords = 8 # 32-bit words.  5 for Dgram with pulseId, 3 for Xtc 
        self._header = np.fromfile(f,dtype=np.uint32,count=headerwords)
        self._xtcsize = 12 # bytes.
        self._payload = np.fromfile(f,dtype=np.uint8,count=self.extent()-self._xtcsize)
    def pulseidlow(self):
        """Return header word 0."""
        return self._header[0]
    def pulseidhigh(self):
        """Return header word 1."""
        return self._header[1]
    def timelow(self):
        """Return header word 2."""
        return self._header[2]
    def timehigh(self):
        """Return header word 3."""
        return self._header[3]
    def env(self):
        """Return header word 4."""
        return self._header[4]
    def transitionId(self):
        """Return bits 24-27 of header word 1, ``(pulseidhigh() >> 24) & 0xf``."""
        return (self.pulseidhigh()>>24)&0xf
    def control(self):
        """Return bits 24-31 of header word 1, ``(pulseidhigh() >> 24) & 0xff``."""
        return (self.pulseidhigh()>>24)&0xff
    def extent(self):
        """Return header word 7."""
        return self._header[7]
    def next(self):
        """Return ``extent() + 12``."""
        return self.extent()+self._xtcsize
    def data(self):
        """Return the header array (all 8 words)."""
        return self._header
    def writeNoPulseId(self,outfile):
        # put the control byte in the top part of env
        """Write the datagram to ``outfile`` without header words 0-1.

        The top byte of header word 4 is first replaced by ``control()``; then header words 2-7 and the payload are written with ``tofile``.
        """
        self._header[4] = (self._header[4]&0xffffff)|(self.control()<<24)
        # remove the 64-bit pulseid/control word
        self._header[2:].tofile(outfile)
        self._payload.tofile(outfile)

assert len(sys.argv)==3
infname = sys.argv[1]
outfname = sys.argv[2]

infile = open(infname,'r')
outfile = open(outfname,'w')
try:
    while(1):
        dg = OldDgram(infile)
        #print(dg.transitionId(),dg.extent())
        dg.writeNoPulseId(outfile)
except: # happens on end of file
    print('done')
    infile.close()
    outfile.close()
