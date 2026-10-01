"""Script `dgram_add_beginstep.py <input.xtc2> <output.xtc2>`: copy all dgrams, adding a BeginStep after each BeginRun.

Each BeginRun dgram (transition id 4) is written a second time with its transition id set to 6 (BeginStep). A count is printed every 100 dgrams; the loop ends at the first exception (end of file), printing "done".

Notes
-----
The code runs at import time.
"""
import numpy as np
import sys

class Dgram:
    """Minimal reader of one xtc2 dgram from an open file.

    The constructor reads the 6-word uint32 header (3 words for the dgram, 3 for the xtc, per the
    code comment) and then `extent() - 12` payload bytes.
    """
    def __init__(self,f):
        headerwords = 6 # 32-bit words. 3 for Dgram, 3 for Xtc 
        self._header = np.fromfile(f,dtype=np.uint32,count=headerwords)
        self._xtcsize = 12 # bytes
        self._payload = np.fromfile(f,dtype=np.uint8,count=self.extent()-self._xtcsize)
    def timelow(self):
        """Return header word 0."""
        return self._header[0]
    def timehigh(self):
        """Return header word 1."""
        return self._header[1]
    def env(self):
        """Return header word 2 (the env word)."""
        return self._header[2]
    def transitionId(self):
        """Return `(env() >> 24) & 0xf`, bits 24 to 27 of the env word."""
        return (self.env()>>24)&0xf
    def control(self):
        """Return `(env() >> 24) & 0xff`, bits 24 to 31 of the env word."""
        return (self.env()>>24)&0xff
    def extent(self):
        """Return header word 5, the extent used to size the payload."""
        return self._header[5]
    def next(self):
        """Return `extent() + 12`."""
        return self.extent()+self._xtcsize
    def data(self):
        """Return the header word array (not the payload)."""
        return self._header
    def write(self,outfile):
        """Write the header words and then the payload to `outfile` with `ndarray.tofile`."""
        self._header.tofile(outfile)
        self._payload.tofile(outfile)

assert len(sys.argv)==3
infname = sys.argv[1]
outfname = sys.argv[2]

infile = open(infname,'r')
outfile = open(outfname,'w')
try:
    ndg = 0
    while(1):
        dg = Dgram(infile)
        #print('----',dg.transitionId(),dg.extent())
        dg.write(outfile)
        if dg.transitionId()==4: # beginrun
            old = dg._header[2]
            dg._header[2] = old&0xf0ffffff | (6<<24) # switch to beginstep
            dg.write(outfile)
        ndg += 1
        if ndg%100 == 0: print('Event:',ndg)
except Exception as e: # happens on end of file
    print('done')
    infile.close()
    outfile.close()
