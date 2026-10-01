"""Detector interfaces for epics and PV information tables, PVs, encoders and a test float detector."""
import sys
from psana.detector.detector_impl import DetectorImpl
from amitypes import Array2d
import logging
from psana.detector.NDArrUtils import info_ndarr #, shape_nda_as_3d, reshape_to_3d # shape_as_3d, shape_as_3d
from psana.detector.areadetector import AreaDetectorRaw, sgs
import numpy as np

# create a dictionary that can be used to look up other
# information about an epics variable.  the key in
# the dictionary is the "detname" of the epics variable
# (from "detnames -e") which can be either the true (ugly)
# epics name or a nicer user-defined name. the most obvious
# way to use this information would be to retrieve the
# real epics name from the "nice" user-defined detname.

class epicsinfo_epicsinfo_1_0_0(DetectorImpl):
    """Table of information about epics variables, built from the `epicsinfo` entries of the configs.

    Calling the object (no arguments) returns the table. For each attribute n of an epicsinfo object
    (except `keys` and names starting with "_"), `table[n]` maps the comma-separated names in `keys`
    to the newline-separated parts of attribute n. The code comment says n is the detname of an
    epics variable, so the table can, for example, give the real epics name of a user-defined name.
    """
    def __init__(self, *args):
        super().__init__(*args)
        self._infodict={}
        for c in self._configs:
            if hasattr(c,'epicsinfo'):
                for seg,value in c.epicsinfo.items():
                    names = getattr(value,'epicsinfo')
                    keys = names.keys.split(',')
                    for n in dir(names):
                        if n.startswith('_') or n=='keys': continue
                        if n not in self._infodict: self._infodict[n]={}
                        values = getattr(names,n).split('\n')
                        for k,v in zip(keys,values): self._infodict[n][k]=v
    def __call__(self):
        return self._infodict

class pvdetinfo_pvdetinfo_1_0_0(DetectorImpl):
    """Table of information built from the `pvdetinfo` entries of the configs.

    Calling the object (no arguments) returns the table. For each attribute n of a pvdetinfo object
    (except `keys` and names starting with "_"), `table[n]` maps the comma-separated names in `keys`
    to the comma-separated parts of attribute n.
    """
    def __init__(self, *args):
        super().__init__(*args)
        self._infodict={}
        for c in self._configs:
            if hasattr(c,'pvdetinfo'):
                for seg,value in c.pvdetinfo.items():
                    names = getattr(value,'pvdetinfo')
                    keys = names.keys.split(',')
                    for n in dir(names):
                        if n.startswith('_') or n=='keys': continue
                        if n not in self._infodict: self._infodict[n]={}
                        values = getattr(names,n).split(',')
                        for k,v in zip(keys,values): self._infodict[n][k]=v

    def __call__(self):
        return self._infodict

class pv_raw_1_0_0(DetectorImpl):
    """Detector interface for detector type `pv`, software `raw`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super().__init__(*args)
        self._add_fields()

class encoder_raw_0_0_1(DetectorImpl):
    """Detector interface for detector type `encoder`, software `raw`, version 0.0.1.

    `value` returns `encoderValue[0] * 1e-6 * scale[0]` of segment 0 (channel 0 only).
    """
    def __init__(self, *args):
        super().__init__(*args)
    def value(self,evt) -> float:
        """
        From Zach:
        “Scale” is copied from the configured “units per encoderValue”
        configuration. So a scale of “6667” means we have 6667 units per count.
        What is the unit? Well, I coded it to be “nanometers per count”
        for the average axis that is controlled in millimeters, since for
        most axes this ends up being an integer, but this axis is controlled
        in microradians, so that “normal case” conversion doesn’t really fit.
        Checking the code, the configured scale for the encoder is 0.0066667
        urads/count. I guess that makes sense since you’d usually multiply
        by 1e-6 to go from mm to nm.

        So to get the “real motor position” you would in general do:
        Position (real units) = encoderValue * scale * 1e-6
        Which works for the current encoderValue and the real position
        shown in the screen.

        Though clearly the scale is rounded in this case, with a true
        value of 2/3 * 1e4

        The Controls group has conventions of mm/urad for linear/rotary
        motion units, so this routine returns urad for the rix mono encoder.
        """
        segments = self._segments(evt)
        if segments is None: return None
        # NOTE: here we only return the first channel of the array to
        # make it easier for the users to use.  If we go to multi-channel in future
        # we could update the version number of the raw data and have
        # another det xface that returns all channels (leaving out the [0]
        # in the "encoderValue" and "scale" below). - cpo 09/28/21
        # note that the order of operations matters here: if
        # we multiply the two numpy array values together we can overflow
        # a uint32.  so convert to float first.
        return (segments[0].encoderValue[0]*1e-6)*segments[0].scale[0]

class encoder_raw_2_0_0(encoder_raw_0_0_1):
    """Detector interface for detector type `encoder`, software `raw`, version 2.0.0.

    `value` returns `encoderValue[0] * scale[0] / scaleDenom[0]` when `scaleDenom[0]` > 0, and the
    version 0.0.1 result otherwise.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def value(self,evt) -> float:
        """
        The Controls group has conventions of mm/urad for linear/rotary
        motion units, so this routine returns urad for the rix mono encoder.
        """
        segments = self._segments(evt)
        if segments is None: return None
        # if scaleDenom > 0, multiply by (float)scale/(float)scaleDenom.
        # Otherwise, inherit from the parent class.
        if (segments[0].scaleDenom[0] > 0):
            return segments[0].encoderValue[0]*(float(segments[0].scale[0])/float(segments[0].scaleDenom[0]))
        else:
            return super().value(evt)

class encoder_raw_2_1_0(encoder_raw_2_0_0):
    """Detector interface for detector type `encoder`, software `raw`, version 2.1.0.

    `value` returns the same as in version 2.0.0.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def value(self,evt) -> float:
        """
        Version 2.1.0 adds innerCount field.  The return value is unaffected.
        """
        return super().value(evt)

class encoder_raw_3_0_0(DetectorImpl):
   """Detector interface for detector type `encoder`, software `raw`, version 3.0.0.

   The fields are read as scalars: `value` returns `encoderValue * scale / scaleDenom` when
   `scaleDenom` > 0, otherwise `encoderValue * 1.0`.
   """
   def __init__(self, *args):
       super().__init__(*args)
   def value(self,evt) -> float:
       """
       Version 3.0.0 addresses fields as scalars, not as arrays.
       """
       segments = self._segments(evt)
       if segments is None: return None
       # if scaleDenom > 0, multiply by (float)scale/(float)scaleDenom.
       # Otherwise, multiply by 1.0.
       if (segments[0].scaleDenom > 0):
           return segments[0].encoderValue*(float(segments[0].scale)/float(segments[0].scaleDenom))
       else:
           return segments[0].encoderValue*1.0

class hrencoder_raw_0_1_0(DetectorImpl):
    """High rate encoder.

    The hrencoder detector returns 4 fields:
        position - The encoder value/position.
        missedTrig_cnt - Missed triggers
        error_cnt - Number of errors.
        latches - Only 3 bits of this integer correspond to the latch status.
    """
    def __init__(self, *args):
        super().__init__(*args)

    def value(self, evt) -> float:
        """Return the `position` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        segments = self._segments(evt)

        if segments is None:
            return None

        return segments[0].position

class encoder_interpolated_3_0_0(encoder_raw_3_0_0):
    """Detector interface for detector type `encoder`, software `interpolated`, version 3.0.0.

    `value` returns the same as `encoder_raw_3_0_0.value`.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def value(self,evt) -> float:
        """
        Version 3.0.0 addresses fields as scalars, not as arrays.
        """
        return super().value(evt)


# Test
class justafloat_simplefloat32_1_2_4(DetectorImpl):
    """Detector interface for detector type `justafloat`, software `simplefloat32`, version 1.2.4.

    Marked as a test class by the code comment.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def value(self,evt) -> float:
        """Return the `valfloat32` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].valfloat32

# EOF
