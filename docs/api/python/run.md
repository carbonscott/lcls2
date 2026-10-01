# psana.psexp.run

The run classes yielded by `ds.runs()`. `Run` is the base class with the
methods most user code calls: `events()` (one `Event` per L1Accept),
`steps()` (one `Step` per BeginStep), `Detector(name, accept_missing=False, **kwargs)`,
and the properties `detnames`, `epicsinfo`, `scaninfo`, `xtcinfo`. Which
subclass you get depends on the data source:

| Class | Data source |
|---|---|
| `RunSerial` | `SerialDataSource` (`exp=`, one process) |
| `RunSingleFile` | `SingleFileDataSource` (`files=`) |
| `RunShmem` | `ShmemDataSource` (`shmem=`) |
| `RunDrp` | `DrpDataSource` (`drp=`) |
| `RunSmallData` | created internally (`eventbuilder_manager.py`, `smdreader_manager.py`) and passed to `smd_callback` |
| `RunParallel` | `MPIDataSource`; defined in [`psana.psexp.mpi_ds`](mpi_ds.md) |

See [DataSource, Run and the event loop](../../features/datasource-run-events.md)
and [Detector interface](../../features/detector-interface.md).

::: psana.psexp.run
