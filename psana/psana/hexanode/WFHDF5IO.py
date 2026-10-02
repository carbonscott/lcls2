
"""
Class :py:class:`WFHDF5IO` - HDF5 I/O for waveforms
===============================================================

Usage ::

    # Import and create object
    #--------------------------
    from psana.hexanode.WFHDF5IO import open_output_h5file, open_input_h5file

    # **kwargs - uses run, exp, tdc_resolution, etc. to add in hdf5 file

    # Recording hdf5
    #----------------

    from psana.hexanode.WFPeaks import WFPeaks
    wfpeaks = WFPeaks(**kwargs)

    f = open_output_h5file(self, wfpeaks, './test.h5')

    # in the event loop:
        # wfs,wts = input arrays of waveforms and sample times, shape=(nchannels, nsamples)
        wfpeaks.proc_waveforms(wfs, wts)
        f.add_event_to_h5file()

    # Reading hdf5
    #--------------

    f = open_input_h5file(self, './test.h5')

    # event loop:
    while f.next_event():
        # Access methods
        #----------------
        nevts  = f.events_in_h5file()
        i      = f.event_number()
        tdcsec = f.tdcsec()
        tdc_ns = f.tdc_ns()
        nhits  = f.number_of_hits()
        nhits, tdcsec = f.peak_arrays()

Created on 2019-11-07 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

import h5py
from time import time
from psana.pyalgos.generic.Utils import str_kwargs
#import numpy as np
#from psana.pyalgos.generic.NDArrUtils import print_ndarr

class WFHDF5IO:

    """Write per-event peak results (hit counts and peak times) of a waveform peak finder to an HDF5 file with h5py, and read them back.

    Keyword arguments 'run', 'exp', 'tdc_resolution' (default 0.250) and 'size_increment' (default 4096) are stored as attributes. ``__del__`` closes any open input or output file.
    """
    def __init__(self, **kwargs):
        """
        """
        logger.debug(str_kwargs(kwargs, title='WFHDF5IO input parameters:'))
        self._of = None
        self._if = None
        self.RUN             = kwargs.get('run', 0)
        self.EXP             = kwargs.get('exp', 'test1234')
        self.TDC_RESOLUTION  = kwargs.get('tdc_resolution', 0.250) # ns
        self._size_increment = kwargs.get('size_increment', 4096)


    def open_output_h5file(self, fname, wfpeaks):
        """Create HDF5 file ``fname`` for writing and its datasets.

        Creates scalar datasets run, experiment, start_time, stop_time, proc_time, tdc_res_ns, nevents and resizable datasets event_number, event_time, nhits (events x channels) and tdcsec (events x channels x hits), sized by ``wfpeaks.NUM_CHANNELS`` and ``wfpeaks.NUM_HITS``. Records the start time.
        """
        self._nev = 0
        self._nevmax = self._size_increment
        self._wfpeaks        = wfpeaks
        self.NUM_CHANNELS    = wfpeaks.NUM_CHANNELS # kwargs.get('numchs',5) #  (int) - number
        self.NUM_HITS        = wfpeaks.NUM_HITS     # kwargs.get('numhits',16) # (int) - maximal

        self._of = h5py.File(fname,'w')
        dtype_str = h5py.special_dtype(vlen=str)
        self.h5ds_run           = self._of.create_dataset('run',          (1,), dtype=dtype_str)
        self.h5ds_exp           = self._of.create_dataset('experiment',   (1,), dtype=dtype_str)
        self.h5ds_start_time    = self._of.create_dataset('start_time',   (1,), dtype='f')
        self.h5ds_stop_time     = self._of.create_dataset('stop_time',    (1,), dtype='f')
        self.h5ds_proc_time     = self._of.create_dataset('proc_time',    (1,), dtype='f')
        self.h5ds_tdc_res_ns    = self._of.create_dataset('tdc_res_ns',   (1,), dtype='f')
        self.h5ds_nevents       = self._of.create_dataset('nevents',      (1,), dtype='i')
        self.h5ds_event_number  = self._of.create_dataset('event_number', (self._nevmax,), dtype='i', maxshape=(None,))
        self.h5ds_event_time    = self._of.create_dataset('event_time',   (self._nevmax,), dtype='f', maxshape=(None,))
        self.h5ds_nhits  = self._of.create_dataset('nhits', (self._nevmax, self.NUM_CHANNELS),\
                                                   dtype='i', maxshape=(None, self.NUM_CHANNELS))
        self.h5ds_tdcsec = self._of.create_dataset('tdcsec', (self._nevmax, self.NUM_CHANNELS, self.NUM_HITS),\
                                                   dtype='f', maxshape=(None, self.NUM_CHANNELS, self.NUM_HITS))
        self._start_time_sec = time()


    def close_output_h5file(self):
        """Shrink the per-event datasets to the number of written events, fill the scalar datasets (times, event count, TDC resolution, run, experiment) and close the output file.

        Does nothing if no output file is open.
        """
        if self._of is None: return

        self._stop_time_sec = time()
        self._resize_h5_datasets(self._nev)
        self.h5ds_start_time[0] = self._start_time_sec
        self.h5ds_stop_time[0]  = self._stop_time_sec
        self.h5ds_proc_time[0]  = self._stop_time_sec - self._start_time_sec
        self.h5ds_nevents[0]    = self._nev
        self.h5ds_tdc_res_ns[0] = self.TDC_RESOLUTION
        self.h5ds_run[0]        = str(self.RUN)
        self.h5ds_exp[0]        = self.EXP
        logger.debug('Close output file: %s' % self._of.filename)
        self._of.close()
        self._of = None


    def _resize_h5_datasets(self, size=None):
        self._nevmax = self._nevmax + self._size_increment if size is None else size
        self._of.flush()
        self.h5ds_nhits       .resize(self._nevmax, axis=0)   # or dset.resize((20,1024))
        self.h5ds_tdcsec      .resize(self._nevmax, axis=0)   # or dset.resize((20,1024))
        self.h5ds_event_number.resize(self._nevmax, axis=0)
        self.h5ds_event_time  .resize(self._nevmax, axis=0)


    def add_event_to_h5file(self):
        """Append the current results of the peak finder (``_number_of_hits`` and ``_pktsec``), the event index and the current time to the output datasets.

        Asserts that waveforms were processed. Datasets grow by ``size_increment`` only after the event count exceeds the current size, so the write at index equal to the current size happens before any resize.
        """
        assert (self._wfpeaks._wfs_old is not None),\
               "waveforms need to be processed before calling add_event_to_h5file()"
        i = self._nev
        self.h5ds_nhits       [i] = self._wfpeaks._number_of_hits
        self.h5ds_tdcsec      [i] = self._wfpeaks._pktsec
        self.h5ds_event_number[i] = i
        self.h5ds_event_time  [i] = time()
        self._nev += 1
        if self._nev > self._nevmax: self._resize_h5_datasets()


    def open_input_h5file(self, fname='./test.h5'):
        """Open HDF5 file ``fname`` for reading and load its datasets and scalar values.

        Uses dataset 'tdcsec' if present, otherwise 'tdcns' (either may be None); reads nevents, experiment, run, tdc_res_ns, start_time and stop_time, and resets the event counter.
        """
        self._error_flag = 0
        self._nev = 0
        self._if = f = h5py.File(fname,'r')
        self.h5ds_nhits      = f['nhits']
        self.h5ds_tdcsec     = f.get('tdcsec', None) # f['tdcsec'] if 'tdcsec' in f.keys() else None
        self.h5ds_tdc_ns     = f.get('tdcns', None)  # f['tdcns']  if 'tdcns'  in f.keys() else None
        self.h5ds_nevents    = f['nevents'][0]
        self.EXP             = f['experiment'][0]
        self.RUN             = f['run'][0]
        self.TDC_RESOLUTION  = f['tdc_res_ns'][0]
        self._start_time_sec = f['start_time'][0]
        self._stop_time_sec  = f['stop_time'][0]
        logger.debug('File %s has %d records' % (fname, self.h5ds_nevents))


    def close_input_h5file(self):
        """Close the input file if one is open."""
        if self._if is None: return
        logger.debug('Close file: %s' % self._if.filename)
        self._if.close()
        self._if = None


    def next_event(self, nev=None):
        """Load hit counts and peak times (seconds; converted from 'tdcns' if needed) of event ``nev`` or of the next event.

        Returns False when the index is past the last event, otherwise True; the internal counter is incremented in both the ``nev`` and the sequential case.
        """
        i = nev if nev is not None else self._nev
        if i>self.h5ds_nevents-1:
             return False
        self._number_of_hits = self.h5ds_nhits[i]
        self._tdcsec         = self.h5ds_tdcsec[i] if self.h5ds_tdcsec is not None else\
                               self.h5ds_tdc_ns[i] * 1E-9 if self.h5ds_tdc_ns is not None else None
        self._nev += 1
        return True


    def peak_arrays(self)      :
        """Return ``(number_of_hits, tdcsec)`` of the current event."""
        return self._number_of_hits, self._tdcsec
    def number_of_hits(self)   :
        """Return the hit-count array of the current event."""
        return self._number_of_hits
    def tdc_ns(self)           :
        """Return the peak-time array of the current event multiplied by 1e9."""
        return self._tdcsec*1E9
    def tdcsec(self)           :
        """Return the peak-time array of the current event as stored (seconds per the dataset name)."""
        return self._tdcsec
    def tdc_resolution(self)   :
        """Return ``self.TDC_RESOLUTION``."""
        return self.TDC_RESOLUTION
    def events_in_h5file(self) :
        """Return the number of events read from the 'nevents' dataset."""
        return self.h5ds_nevents
    def event_number(self)     :
        """Return the index of the last loaded event (internal counter minus 1)."""
        return self._nev - 1
    def start_time(self)       :
        """Return the start time read from (or recorded for) the file."""
        return self._start_time_sec
    def stop_time(self)        :
        """Return the stop time read from (or recorded for) the file."""
        return self._stop_time_sec

    # interface methods - return arrays through input parameters
    def get_number_of_hits_array(self, arr, maxvalue=None): # arr[:] = self._number_of_hits[:]
        """Copy the hit counts of the current event into ``arr``, clipping each to ``maxvalue``.

        With the default ``maxvalue`` None the comparison raises TypeError in Python 3.
        """
        for i,v in enumerate(self._number_of_hits):
            arr[i] = v if v<maxvalue else maxvalue

    def get_tdc_data_array(self, arr, maxsize=-1):
        """Copy columns ``0:maxsize`` of the current peak-time array into the same columns of ``arr``.

        With the default ``maxsize`` -1 the last column is excluded.
        """
        arr[:,0:maxsize] = self._tdcsec[:,0:maxsize]

    def error_flag(self):
        """Return ``self._error_flag`` (set to 0 by ``open_input_h5file``)."""
        return self._error_flag
    def get_error_text(self, error_flag):
        """Return 'no-error: flag=<n>' with the stored error flag; the ``error_flag`` argument is ignored."""
        return 'no-error: flag=%d' % self._error_flag


    def __del__(self):
        #logger.debug('In WFHDF5IO.__del__')
        self.close_output_h5file()
        self.close_input_h5file()


def open_output_h5file(fname, peaks, **kwargs):
    """Create a ``WFHDF5IO(**kwargs)``, open ``fname`` for writing with peak finder ``peaks`` and return the object."""
    f = WFHDF5IO(**kwargs)
    f.open_output_h5file(fname, peaks)
    return f


def open_input_h5file(fname, **kwargs):
    """Create a ``WFHDF5IO(**kwargs)``, open ``fname`` for reading and return the object."""
    f = WFHDF5IO(**kwargs)
    f.open_input_h5file(fname)
    return f


if __name__ == "__main__":
    print('See example in hexanode/examples/ex-##-quad-*.py')

# EOF
