#from psana.detector.detector_impl import DetectorImpl
"""Detector interfaces for the piranha4 detector type (raw image data and timetool-related fields)."""
from psana.detector.areadetector import DetectorImpl, AreaDetectorRaw
from amitypes import Array1d

class piranha4_raw_2_0_0(AreaDetectorRaw):
    """Area-detector interface for detector type `piranha4`, software `raw`, version 2.0.0.

    `AreaDetectorRaw` subclass whose `raw` returns column 0 of segment 0's `image`. Keyword arguments
    given to the constructor are not passed on.
    """
    def __init__(self, *args, **kwa):
        super().__init__(*args)

    def raw(self,evt) -> Array1d:
        """Return `image[:, 0]` (column 0) of segment 0 of this detector in `evt`, or None if its segments are missing."""
        segs = self._segments(evt)
        if segs is None: return None
        return segs[0].image[:,0]

class piranha4_raw_2_1_0(AreaDetectorRaw):
    """Area-detector interface for detector type `piranha4`, software `raw`, version 2.1.0.

    `AreaDetectorRaw` subclass whose `raw` returns segment 0's whole `image`. Keyword arguments
    given to the constructor are not passed on.
    """
    def __init__(self, *args, **kwa):
        super().__init__(*args)

    def raw(self,evt) -> Array1d:
        """Return the `image` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        segs = self._segments(evt)
        if segs is None: return None
        return segs[0].image

class piranha4_ttfex_1_0_0(DetectorImpl):
    """Detector interface for detector type `piranha4`, software `ttfex`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args, **kwa):
        super(piranha4_ttfex_1_0_0, self).__init__(*args)
        self._add_fields()

class piranha4_ttfex_1_0_1(piranha4_ttfex_1_0_0):
    """Algorithm version 1.0.1 - Address potential race condition.

    Note from GD - 2025/10/22:
    We believe there may have been a race condition which could invalidate results
    stored in the FEX. We think it was possible for parallel threads to modify
    the stored FEX results in `m_flt_position` etc, before the write or caput by
    a competing thread could be done. There were no semaphores or other synchronization
    mechanisms guarding writes and reads to/from these shared member attributes.

    To address this possibility we changed the Piranha4TTFex::analyze function to return
    the results to the caller instead of store them on member attributes.

    This increment in algorithm indicates that this new approach is being used. There is
    no difference in the structure/format of the data from algorithm 1.0.0.
    """
    def __init__(self, *args, **kwa):
        super().__init__(*args, **kwa)

class piranha4_ttavg_1_0_0(DetectorImpl):
    """Detector interface for detector type `piranha4`, software `ttavg`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args, **kwa):
        super(piranha4_ttavg_1_0_0, self).__init__(*args)
        self._add_fields()

class piranha4_simfex_1_0_0(DetectorImpl):
    """Detector interface for detector type `piranha4`, software `simfex`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args, **kwa):
        super(piranha4_simfex_1_0_0, self).__init__(*args, **kwa)
        self._add_fields()
