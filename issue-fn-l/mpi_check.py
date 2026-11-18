"""mpirun -n 3 python mpi_check.py <dir>: read tmoacr019 r4 from <dir> under MPI."""
import sys
from psana import DataSource
ds = DataSource(exp="tmoacr019", run=4, dir=sys.argv[1], max_events=20)
n = sum(1 for r in ds.runs() for _ in r.events())
print(f"rank done, {n} events", flush=True)
