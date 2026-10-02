# psana.psexp.ds_base

`DataSourceBase` is the abstract base class of every data source returned by
[`DataSource`](datasource.md) (`SerialDataSource`, `SingleFileDataSource`,
`MPIDataSource`, `ShmemDataSource`, `DrpDataSource`, `NullDataSource`). Its
constructor reads all the keyword arguments that `DataSource` accepts (`exp`,
`run`, `dir`, `files`, `max_events`, `batch_size`, `detectors`, `xdetectors`,
`small_xtc`, `timestamps`, `live`, `skip_calib_load`, ...); unknown keywords
are logged as "Unrecognized kwarg" and ignored. It also finds the xtc2 and
small-data files of a run and provides `smalldata()`, `unique_user_rank()`,
`is_bd()` and `is_srv()`. Subclasses implement `runs()` and `is_mpi()`.

`DsParms` is the dataclass of parameters that is passed from the data source
to its runs.

The "Keyword Arguments" list in the `DataSourceBase` docstring below is not in
a format the generator recognizes, so it is shown as one paragraph. The table
of commonly used keywords in
[DataSource, Run and the event loop](../../features/datasource-run-events.md#datasourcekwargs)
gives the defaults read in `__init__`. Two entries of the docstring list are
narrower than the code: `run` may also be a list of run numbers
(`_setup_runnum_list` accepts an int or a list, and any other type raises
`InvalidDataSourceArgument`), and `skip_calib_load` defaults to `[]`, a list
of detector names, or may be the string `"all"` (checked in
`Run._setup_run_calibconst`).

See [DataSource, Run and the event loop](../../features/datasource-run-events.md).

::: psana.psexp.ds_base
