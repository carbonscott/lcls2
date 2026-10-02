# psana.psexp.drp_ds

`DrpDataSource` is returned by `DataSource(drp=...)` when none of `shmem`,
`exp` or `files` is given (see [psana.datasource](datasource.md)). It reads
dgrams through `DgramManager(["drp"])`, and its `runs()` yields one `RunDrp`
(see [psana.psexp.run](run.md)) for each BeginRun. The constructor reads the
`drp` object itself; the other keyword arguments are read by
[`DataSourceBase`](ds_base.md).

See [DRP and event building](../../features/drp-eventbuilding.md).

::: psana.psexp.drp_ds
