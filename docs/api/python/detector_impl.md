# psana.detector.detector_impl

`DetectorImpl` is the base class of all detector interface classes
(`det.raw`, `det.fex`, ...). It stores the detector name, DRP class name,
configuration and calibration constants, gives access to the event's data
segments (`_segments(evt)`) and configuration (`config(evt)`), and can create
one accessor method per data field (`_add_fields()`). `MissingDet` is the
placeholder returned by `run.Detector(name, accept_missing=True)` for a
detector that is not in the data.

`_reset()` (called by the constructor) stores, among others, `_det_name`,
`_drp_class_name`, `_calibconst` and `_uniqueid`. `_uniqueid` is the detector
type followed by the id of each segment, joined with `_` (built in
`psana/psana/dgrammanager.py`); `det.raw._uniqueid` is the name to pass to
`calib_constants()` (see [Calibration constants](../../features/calibration.md)).
These attributes have no docstrings, so they are not listed below.

See [Detector interface](../../features/detector-interface.md).

::: psana.detector.detector_impl
