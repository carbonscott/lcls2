"""Detector interfaces for the epixuhr3x2 detector type: empty config interfaces and `epixuhr3x2_raw_0_1_0`."""
import logging

import numpy as np
from amitypes import Array2d, Array3d

import psana.detector.epix_base as eb
from psana.detector.detector_impl import DetectorImpl
import psana.detector.UtilsEpixUHR as ueu
#ndu = ueu.ndu
#cond_msg = eb.ue.cond_msg

logger: logging.Logger = logging.getLogger(__name__)

class epixuhr3x2hw_config_0_1_0(DetectorImpl):
    """Detector interface for detector type `epixuhr3x2hw`, software `config`, version 0.1.0.

    Adds nothing to `DetectorImpl`.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class epixuhr3x2_config_0_1_0(DetectorImpl):
    """Detector interface for detector type `epixuhr3x2`, software `config`, version 0.1.0.

    Adds nothing to `DetectorImpl`.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class epixuhr3x2_raw_0_1_0(eb.epix_base):
    """Area-detector interface for detector type `epixuhr3x2`, software `raw`, version 0.1.0.

    `epix_base` subclass. The constructor sets the gain modes and states from `UtilsEpixUHR`, the
    segment geometry "EPIXUHR3X2:V1", the default geometry file
    `pscalib/geometry/data/geometry-def-epixuhr3x2-02.data`, gain bit 0 and data mask 0x0FFE;
    `raw` and `calib` use `UtilsEpixUHR.raw_v01` and `UtilsEpixUHR.calib_v02`.
    """
    def __init__(self, *args, **kwargs):
        eb.epix_base.__init__(self, *args, **kwargs)
        self._gain_modes = ueu.GAIN_MODES # ('FHG', 'FMG', 'FLG1', 'FLG2', 'AHLG1', 'AHLG2', 'AMLG1', 'AMLG2')
        self._gain_states = ueu.GAIN_STATES # GAIN_MODES + ('AHLG1_L', 'AHLG2_L', 'AMLG1_L', 'AMLG2_L') # 12 total
        self._store_ = None
        self._counter_image = 0
        self._seg_geo = eb.sgs.Create(segname='EPIXUHR3X2:V1')
        self._path_geo_default = 'pscalib/geometry/data/geometry-def-epixuhr3x2-02.data'
        self._data_gain_bitnum = 0 # LSB (right-most) is gain bit
        self._data_bit_mask = 0x0FFE # 11-bit data mask (bits 2-12)
        self._dark_factor = 0.5 # factor applied to pedestals, pixel_rms, pixel_min, pixel_max before saving constants in repository

    def _cbits_config_segment(self, cob):
        """cob=det.raw._seg_configs()[<seg-ind>].config - segment configuration object, where self=det.raw
           returns segment gain control bits # shape=(336, 576)
        """
        return ueu.cbits_config_segment_3x2(cob)

    def raw(self, evt, sh_seg=(336,576)) -> Array3d:
        """Return the raw data of all segments as one uint16 array built by `UtilsEpixUHR.raw_v01`.

        The shape is (largest segment number + 1,) + `sh_seg`; each segment's six ASIC arrays are
        rearranged into one `sh_seg` panel. Returns None if `evt` is None or the segments are missing.
        """
        return ueu.raw_v01(self, evt, sh_seg=sh_seg)

    def calib(self, evt, **kwa) -> Array3d:
        """overrides lcls2/psana/psana/detector/epix_base.py epix_base.calib"""
        return ueu.calib_v02(self, evt, **kwa)

#    def image(self, evt, **kwa) -> Array2d: # see in areadetector.py
#        """temporary re-implement AreaDetector.image
#           NOW HIDDEN: returns raw[0,:] 2-d temporary image for a single panel raw data (1, 336, 576)"""
#        return ueu.image_v01(self, evt, **kwa)

# EOF
