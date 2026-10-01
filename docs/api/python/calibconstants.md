# psana.detector.calibconstants

`CalibConstants` wraps the calibration constants of one detector
(`det.calibconst`, a dict `{ctype: (data, metadata)}` fetched from the
calibration database when the run is opened) and provides convenience
accessors (`pedestals()`, `rms()`, `gain()`, `gain_factor()`, `status()`),
geometry (`geo()`, pixel coordinates and indexes) and `image(nda, ...)`. Area
detectors create it on demand (`det.raw._calibconstants()`).

See [Calibration constants](../../features/calibration.md).

::: psana.detector.calibconstants
