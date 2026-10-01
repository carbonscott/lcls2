# psana.detector.detector_impl

`DetectorImpl` is the base class of all detector interface classes
(`det.raw`, `det.fex`, ...). It stores the detector name, DRP class name,
configuration and calibration constants, gives access to the event's data
segments (`_segments(evt)`) and configuration (`config(evt)`), and can create
one accessor method per data field (`_add_fields()`). `MissingDet` is the
placeholder returned by `run.Detector(name, accept_missing=True)` for a
detector that is not in the data.

See [Detector interface](../../features/detector-interface.md).

::: psana.detector.detector_impl
