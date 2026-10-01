# Python API reference

These pages are generated from the source code by
[mkdocstrings](https://mkdocstrings.github.io/) with the
[griffe](https://mkdocstrings.github.io/griffe/) static analyzer. The code is
parsed, never imported, so the pages build without the compiled extensions
(`psana.dgram`, the Cython modules, ...). Two consequences:

- Objects that only exist in compiled code (`.pyx`, `.cc`) do not appear here.
  For the C++ side see the [C++ API](../cpp/index.html) (Doxygen).
- Docstrings are rendered as written. The repository is being documented
  gradually, so some objects only show a signature. Attributes without a
  docstring are hidden (see `docs/hooks/griffe_extensions.py`).

## Curated modules

The pages below cover the user-facing entry points. Each one starts with a
short orientation written for these docs, followed by the generated reference.

| Module | What it contains |
|---|---|
| [`psana.datasource`](datasource.md) | The `DataSource` factory function. |
| [`psana.psexp.ds_base`](ds_base.md) | `DataSourceBase`, the base class of all data sources, and its keyword arguments. |
| [`psana.psexp.run`](run.md) | The `Run` base class and the serial/single-file/shmem/DRP/smalldata run classes. |
| [`psana.event`](event.md) | `Event`, the object yielded by `run.events()`. |
| [`psana.dgrammanager`](dgrammanager.md) | `DgramManager`, which reads dgrams from files, shared memory or the DRP. |
| [`psana.psexp.mpi_ds`](mpi_ds.md) | `MPIDataSource` and `RunParallel` (MPI mode). |
| [`psana.psexp.shmem_ds`](shmem_ds.md) | `ShmemDataSource` (shared-memory mode). |
| [`psana.smalldata`](smalldata.md) | `SmallData` (HDF5 output from MPI jobs) and its `Server`. |
| [`psana.detector.detector_impl`](detector_impl.md) | `DetectorImpl`, the base class of detector interfaces. |
| [`psana.detector.areadetector`](areadetector.md) | `AreaDetector` / `AreaDetectorRaw` (`raw`, `calib`, `image`). |
| [`psana.detector.calibconstants`](calibconstants.md) | `CalibConstants`, access to calibration constants and geometry. |
| [`psdaq.control.control`](control.md) | `CollectionManager` and the DAQ control process. |
| [`psdaq.control.DaqControl`](daqcontrol.md) | `DaqControl`, the client API used by DAQ scripts. |

Only modules that parse with Python 3 are listed; some files in the repository
are Python 2 only and are deliberately not referenced.
