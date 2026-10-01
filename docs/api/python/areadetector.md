# psana.detector.areadetector

Methods common to area (pixel) detectors. `AreaDetector` adds access to
calibration constants and geometry (underscore-prefixed helpers such as
`_pedestals()`, `_gain()`, `_mask()`, `_pixel_coords()`) and `image(evt, ...)`;
`AreaDetectorRaw` adds `raw(evt)` and the generic `calib(evt)`,
`(raw - pedestals) * gain_factor * mask`. Concrete detector classes (ePix,
Jungfrau, Opal, ...) in `psana/psana/detector/` derive from these and override
`calib` where needed. This module is the example area-detector module for the
API reference; `epix10ka.py` and `jungfrau.py` follow the same pattern.

See [Detector interface](../../features/detector-interface.md) and
[Calibration constants](../../features/calibration.md).

::: psana.detector.areadetector
