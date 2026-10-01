"""Simple detector interface classes (subclasses of `DetectorImpl`) used for tests, test stands and
early development, as the code comments describe.

`psana.detector.detectors` imports them all; the class names follow the
`<dettype>_<software>_<major>_<minor>_<micro>` pattern that `DgramManager` looks up.
"""
import numpy as np
from psana.detector.detector_impl import hiddenmethod, DetectorImpl
from amitypes import Array1d, Array2d, Array3d

# For testing quadanode (this uses Cython for speed)
from psana.quadanode import waveforms, times

class hsd_raw_0_0_0(DetectorImpl):
    """Detector interface for detector type `hsd`, software `raw`, version 0.0.0.

    `calib` returns a fixed array of zeros.
    """
    def __init__(self, *args):
        super(hsd_raw_0_0_0, self).__init__(*args)
    def calib(self, evt) -> Array1d:
        """Return `np.zeros((5))`, five float zeros, for any event; `evt` is not used."""
        return np.zeros((5))

class pnccd_raw_1_2_3(DetectorImpl):
    """Test detector produced by dgrampy"""
    def __init__(self, *args):
        super(pnccd_raw_1_2_3, self).__init__(*args)
    def calib(self, evt) -> Array3d:
        """Return the `calib` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].calib
    def photon_energy(self, evt):
        """Return the `photon_energy` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].photon_energy

class hexanode_raw_0_0_1(DetectorImpl):
    """Detector interface for detector type `hexanode`, software `raw`, version 0.0.1.

    `waveforms` and `times` return rows 2 to 6 of the corresponding arrays of segment 0.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def waveforms(self, evt):
        """Return `waveforms[2:7, ...]` (rows 2 to 6) of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segments = self._segments(evt)
        return segments[0].waveforms[2:7,...]
    def times(self, evt):
        """Return `times[2:7, ...]` (rows 2 to 6) of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segments = self._segments(evt)
        return segments[0].times[2:7,...]

# for tmo-fex simulated data test
class quadanode_fex_4_5_6(DetectorImpl):
    """Detector interface for detector type `quadanode`, software `fex`, version 4.5.6.

    The code comment says it is for the tmo-fex simulated data test; `waveforms` and `times`
    call the Cython functions of the same names in `psana.quadanode` with 5 channels per detector.
    """
    def __init__(self, *args):
        super().__init__(*args)

    def waveforms(self, evt, n_dets=1):
        """ Returns list of fex waveforms for `segid` channel.

        List of segments/ channels:
        MCP, X1, X2, Y1, Y2

        Converts 1D waveform into a list of waveforms using lengths array
        as delimiters.
        """
        return waveforms(evt, self, n_dets=n_dets, n_chans_per_det=5)

        #wf1d = self._segments(evt)[segid].waveforms
        #lengths = self._segments(evt)[segid].lengths
        #n_wf = len(lengths)
        #waveforms = []
        #for i in range(n_wf):
        #    st = np.sum(lengths[:i])
        #    en = st + lengths[i]
        #    waveforms.append(wf1d[st:en])
        #return waveforms

    def times(self, evt, n_dets=1):
        """Return the `startpos` field of segments 0 to `n_dets` * 5 - 1 as a dict keyed by segment id.

        Calls `psana.quadanode.times(evt, self, n_dets=n_dets, n_chans_per_det=5)`.
        """
        return times(evt, self, n_dets=n_dets, n_chans_per_det=5)

        #startpos = self._segments(evt)[segid].startpos
        #return startpos

# for dgrampy test
class hsd_fex_4_5_6(DetectorImpl):
    """Detector interface for detector type `hsd`, software `fex`, version 4.5.6.

    The code comment says it is for the dgrampy test.
    """
    def __init__(self, *args):
        super(hsd_fex_4_5_6, self).__init__(*args)
    def calib(self, evt) -> Array1d:
        """Return `np.zeros((6))`, six float zeros, for any event; `evt` is not used."""
        return np.zeros((6))
    @hiddenmethod
    def show(self, evt):
        """Print the `valFex`, `strFex` and `arrayFex0` to `arrayFex9` fields of segment 0 of this detector in `evt`.

        Decorated with `hiddenmethod`, so it is skipped when detector attributes are listed for
        `detinfo`. Returns None.
        """
        segs = self._segments(evt)
        print(f'valFex: {segs[0].valFex}')
        print(f'strFex: {segs[0].strFex}')
        print(f'arrayFex0: {segs[0].arrayFex0}')
        print(f'arrayFex1: {segs[0].arrayFex1}')
        print(f'arrayFex2: {segs[0].arrayFex2}')
        print(f'arrayFex3: {segs[0].arrayFex3}')
        print(f'arrayFex4: {segs[0].arrayFex4}')
        print(f'arrayFex5: {segs[0].arrayFex5}')
        print(f'arrayFex6: {segs[0].arrayFex6}')
        print(f'arrayFex7: {segs[0].arrayFex7}')
        print(f'arrayFex8: {segs[0].arrayFex8}')
        print(f'arrayFex9: {segs[0].arrayFex9}')
        #print(f'arrayString: {segs[0].arrayString}')

# for integrating detector test (1) hsd/fast (2) andor/slow
class hsd_raw_0_0_2(DetectorImpl):
    """Detector interface for detector type `hsd`, software `raw`, version 0.0.2.

    The code comment says it is for the integrating-detector test.
    """
    def __init__(self, *args):
        super(hsd_raw_0_0_2, self).__init__(*args)
    def calib(self, evt):
        """Return the `calib` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].calib
class andor_raw_0_0_2(DetectorImpl):
    """Detector interface for detector type `andor`, software `raw`, version 0.0.2.

    The code comment says it is for the integrating-detector test.
    """
    def __init__(self, *args):
        super(andor_raw_0_0_2, self).__init__(*args)
    def calib(self, evt):
        """Return the `calib` field of segment 1 if the event has it, otherwise of segment 0.

        Returns None if this detector's segments are missing from `evt`.
        """
        segs = self._segments(evt)
        if segs is None:
            return None
        if 1 in segs:
            return segs[1].calib
        else:
            return segs[0].calib
class epix_raw_0_0_2(DetectorImpl):
    """Detector interface for detector type `epix`, software `raw`, version 0.0.2."""
    def __init__(self, *args):
        super(epix_raw_0_0_2, self).__init__(*args)
    def calib(self, evt):
        """Return the `calib` field of segment 2 of this detector in `evt`, or None if its segments are missing."""
        segs = self._segments(evt)
        if segs is None:
            return None
        return segs[2].calib

# for the fake cameras in the teststand
class cspad_cspadRawAlg_1_2_3(DetectorImpl):
    """Detector interface for detector type `cspad`, software `cspadRawAlg`, version 1.2.3.

    The code comment says it is for the fake cameras in the teststand.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def raw(self, evt) -> Array2d:
        """Return the `array_raw` field of segment 0, or None if the detector's segments are missing or segment 0 is None."""
        segs = self._segments(evt)
        if segs is None: return None
        if segs[0] is None: return None
        return segs[0].array_raw
class fakecam_raw_2_0_0(cspad_cspadRawAlg_1_2_3):
    """Detector interface for detector type `fakecam`, software `raw`, version 2.0.0.

    Same as `cspad_cspadRawAlg_1_2_3`; adds nothing.
    """
    def __init__(self, *args):
        super().__init__(*args)
class fakecam_cube_2_0_0(DetectorImpl):
    """Detector interface for detector type `fakecam`, software `cube`, version 2.0.0.

    Each method returns one field of segment 0.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def bin(self, evt) -> Array1d:
        """Return the `bin` field of segment 0, or None if the detector's segments are missing or segment 0 is None."""
        segs = self._segments(evt)
        if segs is None: return None
        if segs[0] is None: return None
        return segs[0].bin
    def entries(self, evt) -> Array1d:
        """Return the `entries` field of segment 0, or None if the detector's segments are missing or segment 0 is None."""
        segs = self._segments(evt)
        if segs is None: return None
        if segs[0] is None: return None
        return segs[0].entries
    def value(self, evt) -> Array1d:
        """Return the `value` field of segment 0, or None if the detector's segments are missing or segment 0 is None."""
        segs = self._segments(evt)
        if segs is None: return None
        if segs[0] is None: return None
        return segs[0].value
    def array(self, evt) -> Array3d:
        """Return the `array_raw` field of segment 0, or None if the detector's segments are missing or segment 0 is None."""
        segs = self._segments(evt)
        if segs is None: return None
        if segs[0] is None: return None
        return segs[0].array_raw

# for the pva detector in the teststand
class pva_pvaAlg_1_2_3(DetectorImpl):
    """Detector interface for detector type `pva`, software `pvaAlg`, version 1.2.3.

    The code comment says it is for the pva detector in the teststand.
    """
    def __init__(self, *args):
        super().__init__(*args)
    def raw(self, evt) -> Array1d:
        """Return the `value` field of segment 0, or None if the detector's segments are missing or segment 0 is None."""
        segs = self._segments(evt)
        if segs is None: return None
        if segs[0] is None: return None
        return segs[0].value
class andor_raw_0_0_1(pva_pvaAlg_1_2_3):
    """Detector interface for detector type `andor`, software `raw`, version 0.0.1.

    Same as `pva_pvaAlg_1_2_3`; adds nothing.
    """
    def __init__(self, *args):
        super().__init__(*args)

class cspad_raw_2_3_42(DetectorImpl):
    """Detector interface for detector type `cspad`, software `raw`, version 2.3.42.

    Its methods combine the `arrayRaw` fields of all segments.
    """
    def __init__(self, *args):
        super(cspad_raw_2_3_42, self).__init__(*args)
    def raw(self, evt) -> Array3d:
        # an example of how to handle multiple segments
        """Return the `arrayRaw` fields of segments 0 to n-1 stacked along a new first axis (`np.stack`).

        n is the number of segments in the event. No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return np.stack([segs[i].arrayRaw for i in range(len(segs))])
    def calib(self, evt) -> Array3d:
        """Return `self.raw(evt)` unchanged."""
        return self.raw(evt)
    def image(self, evt) -> Array2d:
        """Return the `arrayRaw` fields of segments 0 to n-1 joined along the first axis (`np.vstack`).

        n is the number of segments in the event. No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return np.vstack([segs[i].arrayRaw for i in range(len(segs))])

class ele_opal_raw_1_2_3(DetectorImpl):
    """Detector interface for detector type `ele_opal`, software `raw`, version 1.2.3."""
    def __init__(self, *args):
        super().__init__(*args)
    def image(self, evt) -> Array2d:
        """Return the `img` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].img

class eventid_valseid_0_0_1(DetectorImpl):
    """Detector interface for detector type `eventid`, software `valseid`, version 0.0.1.

    Each method returns one field of segment 0, or None if the segments are missing.
    """
    def __init__(self, *args):
        DetectorImpl.__init__(self, *args)
    def experiment(self, evt):
        """Return the `experiment` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].experiment if self._segments(evt) is not None else None
    def run(self, evt):
        """Return the `run` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].run        if self._segments(evt) is not None else None
    def fiducials(self, evt):
        """Return the `fiducials` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].fiducials  if self._segments(evt) is not None else None
    def time(self, evt):
        """Return the `time` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].time       if self._segments(evt) is not None else None


class gasdetector_valsgd_0_0_1(DetectorImpl):
    """Detector interface for detector type `gasdetector`, software `valsgd`, version 0.0.1.

    Each method returns one field of segment 0, or None if the segments are missing.
    """
    def __init__(self, *args):
        DetectorImpl.__init__(self, *args)
    def f_11_ENRC(self, evt):
        """Return the `f_11_ENRC` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].f_11_ENRC if self._segments(evt) is not None else None
    def f_12_ENRC(self, evt):
        """Return the `f_12_ENRC` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].f_12_ENRC if self._segments(evt) is not None else None
    def f_21_ENRC(self, evt):
        """Return the `f_21_ENRC` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].f_21_ENRC if self._segments(evt) is not None else None
    def f_22_ENRC(self, evt):
        """Return the `f_22_ENRC` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].f_22_ENRC if self._segments(evt) is not None else None
    def f_63_ENRC(self, evt):
        """Return the `f_63_ENRC` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].f_63_ENRC if self._segments(evt) is not None else None
    def f_64_ENRC(self, evt):
        """Return the `f_64_ENRC` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].f_64_ENRC if self._segments(evt) is not None else None


class xtcavpars_valsxtp_0_0_1(DetectorImpl):
    """Detector interface for detector type `xtcavpars`, software `valsxtp`, version 0.0.1.

    Each method returns the field of the same name of segment 0, or None if the segments are missing.
    """
    def __init__(self, *args):
        DetectorImpl.__init__(self, *args)
    def XTCAV_Analysis_Version      (self, evt):
        """Return the `XTCAV_Analysis_Version` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_Analysis_Version       if self._segments(evt) is not None else None
    def XTCAV_ROI_sizeX             (self, evt):
        """Return the `XTCAV_ROI_sizeX` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_ROI_sizeX              if self._segments(evt) is not None else None
    def XTCAV_ROI_sizeY             (self, evt):
        """Return the `XTCAV_ROI_sizeY` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_ROI_sizeY              if self._segments(evt) is not None else None
    def XTCAV_ROI_startX            (self, evt):
        """Return the `XTCAV_ROI_startX` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_ROI_startX             if self._segments(evt) is not None else None
    def XTCAV_ROI_startY            (self, evt):
        """Return the `XTCAV_ROI_startY` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_ROI_startY             if self._segments(evt) is not None else None
    def XTCAV_calib_umPerPx         (self, evt):
        """Return the `XTCAV_calib_umPerPx` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_calib_umPerPx          if self._segments(evt) is not None else None
    def OTRS_DMP1_695_RESOLUTION    (self, evt):
        """Return the `OTRS_DMP1_695_RESOLUTION` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].OTRS_DMP1_695_RESOLUTION     if self._segments(evt) is not None else None
    def XTCAV_strength_par_S        (self, evt):
        """Return the `XTCAV_strength_par_S` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_strength_par_S         if self._segments(evt) is not None else None
    def OTRS_DMP1_695_TCAL_X        (self, evt):
        """Return the `OTRS_DMP1_695_TCAL_X` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].OTRS_DMP1_695_TCAL_X         if self._segments(evt) is not None else None
    def XTCAV_Amp_Des_calib_MV      (self, evt):
        """Return the `XTCAV_Amp_Des_calib_MV` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_Amp_Des_calib_MV       if self._segments(evt) is not None else None
    def SIOC_SYS0_ML01_AO214        (self, evt):
        """Return the `SIOC_SYS0_ML01_AO214` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].SIOC_SYS0_ML01_AO214         if self._segments(evt) is not None else None
    def XTCAV_Phas_Des_calib_deg    (self, evt):
        """Return the `XTCAV_Phas_Des_calib_deg` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_Phas_Des_calib_deg     if self._segments(evt) is not None else None
    def SIOC_SYS0_ML01_AO215        (self, evt):
        """Return the `SIOC_SYS0_ML01_AO215` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].SIOC_SYS0_ML01_AO215         if self._segments(evt) is not None else None
    def XTCAV_Beam_energy_dump_GeV  (self, evt):
        """Return the `XTCAV_Beam_energy_dump_GeV` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_Beam_energy_dump_GeV   if self._segments(evt) is not None else None
    def REFS_DMP1_400_EDES          (self, evt):
        """Return the `REFS_DMP1_400_EDES` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].REFS_DMP1_400_EDES           if self._segments(evt) is not None else None
    def XTCAV_calib_disp_posToEnergy(self, evt):
        """Return the `XTCAV_calib_disp_posToEnergy` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAV_calib_disp_posToEnergy if self._segments(evt) is not None else None
    def SIOC_SYS0_ML01_AO216        (self, evt):
        """Return the `SIOC_SYS0_ML01_AO216` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].SIOC_SYS0_ML01_AO216         if self._segments(evt) is not None else None


class ebeam_valsebm_0_0_1(DetectorImpl):
    """Detector interface for detector type `ebeam`, software `valsebm`, version 0.0.1.

    Each method returns one field of segment 0, or None if the segments are missing.
    """
    def __init__(self, *args):
        DetectorImpl.__init__(self, *args)
    def Charge(self, evt):
        """Return the `Charge` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].Charge     if self._segments(evt) is not None else None
    def DumpCharge(self, evt):
        """Return the `DumpCharge` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].DumpCharge if self._segments(evt) is not None else None
    def XTCAVAmpl(self, evt):
        """Return the `XTCAVAmpl` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAVAmpl  if self._segments(evt) is not None else None
    def XTCAVPhase(self, evt):
        """Return the `XTCAVPhase` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].XTCAVPhase if self._segments(evt) is not None else None
    def PkCurrBC2(self, evt):
        """Return the `PkCurrBC2` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].PkCurrBC2  if self._segments(evt) is not None else None
    def L3Energy(self, evt):
        """Return the `L3Energy` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        return self._segments(evt)[0].L3Energy   if self._segments(evt) is not None else None


class ebeam_raw_2_3_42(DetectorImpl):
    """Detector interface for detector type `ebeam`, software `raw`, version 2.3.42.

    This module defines `ebeam_raw_2_3_42` three times; only the last definition stays bound to the
    name.
    """
    def __init__(self, *args):
        super(ebeam_raw_2_3_42, self).__init__(*args)
    def energy(self, evt):
        """Return the `energy` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].energy


class cspad_raw_2_3_43(cspad_raw_2_3_42):
    """Detector interface for detector type `cspad`, software `raw`, version 2.3.43.

    Subclass of `cspad_raw_2_3_42` whose `raw` raises NotImplementedError, so the inherited `calib`
    raises it too.
    """
    def __init__(self, *args):
        super(cspad_raw_2_3_43, self).__init__(*args)
    def raw(self, evt) -> None:
        """Raise NotImplementedError; raw data access is not implemented for this version."""
        raise NotImplementedError()

class ebeam_raw_2_3_42(DetectorImpl):
    """Second definition of `ebeam_raw_2_3_42`, identical to the first.

    The third definition below replaces it and is the one bound to the name.
    """
    def __init__(self, *args):
        super(ebeam_raw_2_3_42, self).__init__(*args)
    def energy(self, evt):
        """Return the `energy` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].energy

class ebeam_raw_2_3_42(DetectorImpl):
    """Third and last definition of `ebeam_raw_2_3_42`, the one bound to the name.

    Same as the earlier ones except that `energy` is annotated as returning float.
    """
    def __init__(self, *args):
        super(ebeam_raw_2_3_42, self).__init__(*args)
    def energy(self, evt) -> float:
        """Return the `energy` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].energy

class laser_raw_2_3_42(DetectorImpl):
    """Detector interface for detector type `laser`, software `raw`, version 2.3.42."""
    def __init__(self, *args):
        super(laser_raw_2_3_42, self).__init__(*args)
    def laserOn(self, evt) -> int:
        """Return the `laserOn` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].laserOn

class hsd_raw_2_3_42(DetectorImpl):
    """Detector interface for detector type `hsd`, software `raw`, version 2.3.42."""
    def __init__(self, *args):
        super(hsd_raw_2_3_42, self).__init__(*args)
    def waveform(self, evt) -> Array1d:
        # example of how to check for missing detector in event
        """Return the `waveform` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        if self._segments(evt) is None:
            return None
        else:
            return self._segments(evt)[0].waveform

class camera_raw_0_0_1(DetectorImpl):
    """Detector interface for detector type `camera`, software `raw`, version 0.0.1.

    Calling the object returns `array(evt)`.
    """
    def __init__(self, *args):
        DetectorImpl.__init__(self, *args)
    def array(self, evt) -> Array2d:
        """Return the `array` field of segment 0 of this detector in `evt`, or None if its segments are missing."""
        if self._segments(evt) is None:
            return None
        else:
            return self._segments(evt)[0].array
    def __call__(self, evt) -> Array2d:
        """Alias for self.raw(evt)"""
        return self.array(evt)

# for early cctbx/psana2 development
class cspad_raw_1_2_3(DetectorImpl):
    """Detector interface for detector type `cspad`, software `raw`, version 1.2.3.

    The code comment says it is for early cctbx/psana2 development. Calibration constants are read
    from the detector's calibration dict, whose values are (value, metadata) tuples.
    """
    def __init__(self, *args):
        super(cspad_raw_1_2_3, self).__init__(*args)
    def raw(self, evt):
        #quad0 = self._segments(evt)[0].quads0_data
        #quad1 = self._segments(evt)[0].quads1_data
        #quad2 = self._segments(evt)[0].quads2_data
        #quad3 = self._segments(evt)[0].quads3_data
        #return np.concatenate((quad0, quad1, quad2, quad3), axis=0)
        """Return the `raw` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].raw

    def raw_data(self, evt):
        """Return `self.raw(evt)`."""
        return self.raw(evt)

    def photonEnergy(self, evt):
        """Return the `photonEnergy` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        return self._segments(evt)[0].photonEnergy

    def calib(self, evt):
        """Return the raw data as float64 with pedestals subtracted, then multiplied by the gain mask and gain.

        The gain mask is applied only if the 'gain_mask' constant exists and `gain()` is always 1.0;
        `common_mode_apply` is called but changes nothing. A missing 'pedestals' constant makes the
        subtraction fail with TypeError.
        """
        data = self.raw(evt)
        data = data.astype(np.float64) # convert raw photon counts to float for other math operations.
        data -= self.pedestals()
        self.common_mode_apply(data, None)
        gain_mask = self.gain_mask()
        if gain_mask is not None:
            data *= gain_mask
        data *= self.gain()
        return data

    def image(self, data, verbose=0):
        """Print "cspad.image" and return None; no image is computed and the arguments are not used."""
        print("cspad.image")

    def _fetch(self, key):
        val = None
        if key in self._calibconst:
            val, _ = self._calibconst[key]
        return val

    def pedestals(self):
        """Return the 'pedestals' calibration constant, or None if it is absent."""
        return self._fetch('pedestals')

    def gain_mask(self, gain=0):
        """Return the 'gain_mask' calibration constant, or None if it is absent; `gain` is not used."""
        return self._fetch('gain_mask')

    def common_mode_apply(self, data, common_mode):
        # FIXME: apply common_mode
        """Return `data` unchanged; common-mode correction is not implemented (marked FIXME in the code)."""
        return data

    def gain(self):
        # default gain is set to 1.0 (FIXME)
        """Return 1.0, a fixed default gain (marked FIXME in the code)."""
        return 1.0

    def geometry(self):
        """Return a `GeometryAccess` loaded from the 'geometry' calibration constant (a string).

        Returns None if that constant is absent.
        """
        geometry_string = self._fetch('geometry')
        geometry_access = None
        if geometry_string is not None:
            from psana.pscalib.geometry.GeometryAccess import GeometryAccess
            geometry_access = GeometryAccess()
            geometry_access.load_pars_from_str(geometry_string)
        return geometry_access

class sfx_raw_1_2_3(DetectorImpl):
    """Test detector produced by dgrampy"""
    def __init__(self, *args):
        super(sfx_raw_1_2_3, self).__init__(*args)
    def calib(self, evt) -> Array3d:
        """Return the `calib` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].calib
    def photon_energy(self, evt):
        """Return the `photon_energy` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].photon_energy

    ## peak finder
    def npeaks(self,evt):
        """Return the `npeaks` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].npeaks
    def seg(self,evt):
        """Return the `seg` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].seg
    def row(self,evt):
        """Return the `row` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].row
    def col(self,evt):
        """Return the `col` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].col
    def npix(self,evt):
        """Return the `npix` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].npix
    def amax(self,evt):
        """Return the `amax` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].amax
    def atot(self,evt):
        """Return the `atot` field of segment 0 of this detector in `evt`.

        No missing-data check: raises TypeError if the event does not have all of this detector's segments.
        """
        segs = self._segments(evt)
        return segs[0].atot

class epixhremu_raw_0_0_1(DetectorImpl):
    """Detector interface for detector type `epixhremu`, software `raw`, version 0.0.1.

    Its methods combine the `raw` fields of all segments in sorted segment-id order.
    """
    def __init__(self, *args):
        super().__init__(*args)
    #def raw(self, evt) -> Array2d:
    #    segs = self._segments(evt)
    #    if segs is None: return None
    #    if segs[0] is None: return None
    #    return segs[0].raw
    def raw(self, evt) -> Array3d:
        # an example of how to handle multiple segments
        """Return the `raw` fields of all segments, in sorted segment-id order, stacked along a new first axis (`np.stack`).

        No missing-data check: raises AttributeError if the event does not have all of this detector's
        segments.
        """
        segs = self._segments(evt)
        return np.stack([segs[i].raw for i in sorted(segs.keys())])
    def calib(self, evt) -> Array3d:
        """Return `self.raw(evt)` unchanged."""
        return self.raw(evt)
    def image(self, evt) -> Array2d:
        """Return the `raw` fields of all segments, in sorted segment-id order, joined along the first axis (`np.vstack`).

        No missing-data check: raises AttributeError if the event does not have all of this detector's
        segments.
        """
        segs = self._segments(evt)
        return np.vstack([segs[i].raw for i in sorted(segs.keys())])
