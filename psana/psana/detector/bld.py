"""Detector interfaces for hpsex, hpscp, ebeam, ebeamh, gasdet, bmmon, pcav, pcavh, gmd, xgmd,
feespec, usdusb and scbld data; most generate their accessors from the configuration with
`DetectorImpl._add_fields`.
"""
import numpy as np
import numpy.typing as npt
from psana.detector.detector_impl import DetectorImpl
# for AMI
import typing
import inspect

class hpsex_hpsex_0_0_1(DetectorImpl):
    """Detector interface for detector type `hpsex`, software `hpsex`, version 0.0.1.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(hpsex_hpsex_0_0_1, self).__init__(*args)

        self._add_fields()

    def _info(self,evt):
        # check for missing data
        segments = self._segments(evt)
        if segments is None: return None

        return segments[0]

class hpscp_hpscp_0_0_1(DetectorImpl):
    """Detector interface for detector type `hpscp`, software `hpscp`, version 0.0.1.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(hpscp_hpscp_0_0_1, self).__init__(*args)

        self._add_fields()

    def _info(self,evt):
        # check for missing data
        segments = self._segments(evt)
        if segments is None: return None
        return segments[0]

class ebeam_ebeamAlg_0_7_1(DetectorImpl):
    """Detector interface for detector type `ebeam`, software `ebeamAlg`, version 0.7.1.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(ebeam_ebeamAlg_0_7_1, self).__init__(*args)
        self._add_fields()

class ebeam_raw_2_0_0(ebeam_ebeamAlg_0_7_1):
    """Detector interface for detector type `ebeam`, software `raw`, version 2.0.0.

    Same as `ebeam_ebeamAlg_0_7_1` (fields generated from the configuration); adds nothing.
    """
    def __init__(self, *args):
        super().__init__(*args)

class ebeam_cube_2_0_0(ebeam_ebeamAlg_0_7_1):
    """Detector interface for detector type `ebeam`, software `cube`, version 2.0.0.

    Same as `ebeam_ebeamAlg_0_7_1` (fields generated from the configuration); adds nothing.
    """
    def __init__(self, *args):
        super().__init__(*args)

class ebeamh_raw_2_0_0(ebeam_ebeamAlg_0_7_1):
    """Detector interface for detector type `ebeamh`, software `raw`, version 2.0.0.

    Same as `ebeam_ebeamAlg_0_7_1` (fields generated from the configuration); adds nothing.
    """
    def __init__(self, *args):
        super().__init__(*args)

class ebeamh_cube_2_0_0(ebeam_ebeamAlg_0_7_1):
    """Detector interface for detector type `ebeamh`, software `cube`, version 2.0.0.

    Same as `ebeam_ebeamAlg_0_7_1` (fields generated from the configuration); adds nothing.
    """
    def __init__(self, *args):
        super().__init__(*args)

class gasdet_raw_1_0_0(DetectorImpl):
    """Detector interface for detector type `gasdet`, software `raw`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(gasdet_raw_1_0_0, self).__init__(*args)
        self._add_fields()

class gasdet_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `gasdet`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(gasdet_cube_2_0_0, self).__init__(*args)
        self._add_fields()

class bmmon_raw_1_0_0(DetectorImpl):
    """Detector interface for detector type `bmmon`, software `raw`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(bmmon_raw_1_0_0, self).__init__(*args)
        self._add_fields()

class bmmon_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `bmmon`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(bmmon_cube_2_0_0, self).__init__(*args)
        self._add_fields()

class pcav_raw_2_0_0(DetectorImpl):
    """Detector interface for detector type `pcav`, software `raw`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(pcav_raw_2_0_0, self).__init__(*args)
        self._add_fields()

class pcav_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `pcav`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(pcav_cube_2_0_0, self).__init__(*args)
        self._add_fields()

class pcavh_raw_2_0_0(DetectorImpl):
    """Detector interface for detector type `pcavh`, software `raw`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(pcavh_raw_2_0_0, self).__init__(*args)
        self._add_fields()

class pcavh_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `pcavh`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(pcavh_cube_2_0_0, self).__init__(*args)
        self._add_fields()

class gmd_raw_2_0_0(DetectorImpl):
    """Detector interface for detector type `gmd`, software `raw`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(gmd_raw_2_0_0, self).__init__(*args)
        self._add_fields()

class gmd_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `gmd`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(gmd_cube_2_0_0, self).__init__(*args)
        self._add_fields()

class gmd_raw_2_1_0(DetectorImpl):
    """Detector interface for detector type `gmd`, software `raw`, version 2.1.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(gmd_raw_2_1_0, self).__init__(*args)
        self._add_fields()

class xgmd_raw_2_0_0(DetectorImpl):
    """Detector interface for detector type `xgmd`, software `raw`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(xgmd_raw_2_0_0, self).__init__(*args)
        self._add_fields()

class xgmd_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `xgmd`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(xgmd_cube_2_0_0, self).__init__(*args)
        self._add_fields()

class xgmd_raw_2_1_0(DetectorImpl):
    """Detector interface for detector type `xgmd`, software `raw`, version 2.1.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(xgmd_raw_2_1_0, self).__init__(*args)
        self._add_fields()

class feespec_raw_1_0_0(DetectorImpl):
    """Detector interface for detector type `feespec`, software `raw`, version 1.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super().__init__(*args)
        self._add_fields()

class feespec_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `feespec`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super().__init__(*args)
        self._add_fields()

class usdusb_raw_1_0_0(DetectorImpl):
    """Detector interface for detector type `usdusb`, software `raw`, version 1.0.0.

    Fields are generated from the configuration with `_add_fields()`, and `descriptions` decodes the
    per-channel names. The constructor's docstring lists the fields and calls the device a fast USB
    encoder with 4 channels.
    """
    def __init__(self, *args):
        """Fast USB encoder.

        There are 4 channels.

        Hidden fields:
            Config
                _countMode: uint32_t[4]
                _quadMode:  uint32_t[4]
            FEX Config
                _offset: int32_t[4]
                _scale:  double[4]
                _name:   int8_t[4][48] (actually str[4])
            Raw Data
                _header:    uint8_t[6]
                _din:       uint8_t
                _estop:     uint8_t
                _timestamp: uint32_t
                _count:     uint32_t[4]
                _status:    uint8_t[4]
                _ain:       uint16_t[4]
        Visible field:
            FEX:
                encoder_values: double[4] - (raw_count + offset)*scale
        """
        super().__init__(*args)
        self._add_fields()

    def descriptions(self, evt) -> typing.List[str]:
        """Unpack chars into a list of descriptions per channel"""
        # Holds [4][48] array of chars with descriptive name
        # 4 channels, with max 48 chars per channel description
        str_bytes: npt.NDArray[np.int8] = self._name(evt)
        ch_descs: typing.List[str] = []
        for i in range(4):
            ch_desc: str = str_bytes[i*48:(i+1)*48].tobytes().decode().strip("\x00")
            ch_descs.append(ch_desc)
        return ch_descs

class scbld_raw_1_0_0(DetectorImpl):
    """Detector interface for detector type `scbld`, software `raw`, version 1.0.0.

    On construction one accessor is added per data field of segment key 0 in the config (except
    `software`, `version` and `severity`), returning that field of segment 0 or None if the segments
    are missing. For the i-th such field a `<field>_sevr(evt)` accessor is also added, returning
    `(severity >> (2*i)) & 3` from segment 0, or None if the segments are missing.
    """
    def __init__(self, *args):
        super(scbld_raw_1_0_0, self).__init__(*args)
        self._add_fields_and_severity()

    def _add_fields_and_severity(self):
        for config in self._configs:
            if not hasattr(config,'software'): continue

            seg      = getattr(config.software,self._det_name)
            seg_dict = getattr(seg[0],self._drp_class_name)
            attrs    = [attr for attr in vars(seg_dict) if not (attr=='software' or attr=='version' or attr=='severity')]
            for i,field in enumerate(attrs):
                fd = getattr(seg_dict,field)
                # fd._type, fd._rank
                def func(evt, field=field) -> self._return_types(fd._type,fd._rank):
                    info = self._info(evt)
                    if info is None:
                        return None
                    else:
                        return getattr(info,field)
                setattr(self, field, func)

                def func(evt, field=field, i=i) -> int:
                    info = self._info(evt)
                    if info is None:
                        return None
                    else:
                        return (getattr(info,'severity')>>(i*2))&3
                setattr(self, f'{field}_sevr', func)

class scbld_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `scbld`, software `cube`, version 2.0.0.

    On construction `_add_fields()` adds one method per data field declared in the config (except
    `software` and `version`); each returns that field of segment 0 for an event, or None if the
    detector's segments are missing.
    """
    def __init__(self, *args):
        super(scbld_cube_2_0_0, self).__init__(*args)
        self._add_fields()

