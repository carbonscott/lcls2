"""What the GPU DRP (drp_gpu, psdaq/drpGpu) records.

drp_gpu calibrates every event on the GPU and records what its reducer makes of the result.
The NoOpReducer (psdaq/drpGpu/NoOpReducer.cu) records the calibrated pixels unchanged: the
float32 values as bytes, one uint8 array 'noOp' under the reducer's Names (alg 'noOp' 0.0.0,
detType the DRP's -D type).  calib() returns them as float32, in the panel's shape when the
type has one.
"""

import numpy as np

from psana.detector.detector_impl import DetectorImpl


class _drpgpu_noOp(DetectorImpl):
    shape = None                        # The type's panel, as its GPU code fills it

    def __init__(self, *args):
        super().__init__(*args)

    def calib(self, evt):
        segs = self._segments(evt)
        if not segs:
            return None
        out = []
        for segment in sorted(segs):
            a = np.ascontiguousarray(segs[segment].noOp).view(np.float32)
            if self.shape is not None and a.size == int(np.prod(self.shape)):
                a = a.reshape(self.shape)
            out.append(a)
        return out[0] if len(out) == 1 else np.stack(out)


# Gpu::AreaDetector: as many pixels as the DRP's sim_length kwarg asks for (2 per word)
class fakecam_noOp_0_0_0(_drpgpu_noOp):
    pass


# Gpu::EpixUHRemu: the ePixUHR 3x2 emulator's 336 x 576 panel
class epixuhremu_noOp_0_0_0(_drpgpu_noOp):
    shape = (336, 576)


# Gpu::EpixUHRsim: the GPU DRP's own simulated ePixUHR 3x2 panel, 336 x 576
class epixuhrsim_noOp_0_0_0(_drpgpu_noOp):
    shape = (336, 576)


# Gpu::Jungfrau: one module's 512 x 1024 panel (more modules: one after the other)
class jungfrau_noOp_0_0_0(_drpgpu_noOp):
    shape = (512, 1024)
