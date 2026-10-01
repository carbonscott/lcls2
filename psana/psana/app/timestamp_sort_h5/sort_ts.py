"""Define `TsSort`, which sorts an HDF5 file's rows by its "timestamp" dataset with dask and writes the result with spawned MPI writers."""
from mpi4py import MPI
import os
import sys
import h5py
import numpy as np
import dask.array as da
import dask.dataframe as dd

from psana.app.timestamp_sort_h5.utils import get_dask_client, create_virtual_dataset

from psana import utils


class TsSort:
    """Timestamp sort of the HDF5 file `in_h5` into `out_h5`.

    Parameters
    ----------
    in_h5, out_h5 : str
        Input and output file names.
    chunk_size : int
        Dask chunk length; also passed to the writers.
    n_procs, n_jobs : int
        Passed to `get_dask_client`; `n_procs` is also passed to the writers.
    batch_size : int
        Number of rows per part file.
    n_ranks : int
        Number of writer processes to spawn.
    """
    def __init__(self, in_h5, out_h5, chunk_size, n_procs, n_jobs, batch_size, n_ranks):
        self.in_h5fname = in_h5
        self.out_h5fname = out_h5
        self.chunk_size = chunk_size
        self.batch_size = batch_size
        self.n_ranks = n_ranks
        self.n_procs = n_procs
        self.n_jobs = n_jobs
        self.logger = utils.get_logger(name=utils.get_class_name(self))

    def sort(self):
        """Return the row indexes of the input file's "timestamp" dataset in ascending timestamp order, as an int64 array.

        Uses a dask client from `get_dask_client(n_procs, n_jobs=n_jobs)` and a dask dataframe sort with
        chunks of `chunk_size`; the client and cluster are closed afterwards.
        """
        client, cluster = get_dask_client(self.n_procs, n_jobs=self.n_jobs)
        ts_chunks = (self.chunk_size,)
        in_f = h5py.File(self.in_h5fname, "r")
        da_ts = da.from_array(in_f["timestamp"], chunks=ts_chunks)
        dd_ts = dd.from_array(da_ts, columns=["timestamp"])

        # Sorting (sort_values is not in-place)
        dd_ts_sorted = dd_ts.sort_values("timestamp")

        # Load indices
        inds = dd_ts_sorted.index.values
        inds_arr = np.asarray(inds.compute(), dtype=np.int64)
        in_f.close()
        client.close()
        cluster.close()
        return inds_arr

    def slice_and_write(self, inds_arr):
        # Spawn mpiworkers
        """Write the rows in the order `inds_arr` with spawned MPI writers, then join the part files.

        Spawns `n_ranks` processes running `parallel_h5_write.py`, broadcasts the file names and sizes,
        sends each requesting writer the next `batch_size` slice of indexes, then sends empty messages to
        stop them and builds the virtual dataset with `create_virtual_dataset`. Ends with `Abort(1)` on
        the merged communicator.
        """
        maxprocs = self.n_ranks
        source_dir = os.path.dirname(os.path.abspath(__file__))
        spawn_file = os.path.join(source_dir, "parallel_h5_write.py")
        sub_comm = MPI.COMM_SELF.Spawn(
            sys.executable,
            args=[spawn_file],
            maxprocs=maxprocs,
        )
        common_comm = sub_comm.Merge(False)

        data = {
            "n_procs": self.n_procs,
            "chunk_size": self.chunk_size,
            "in_h5fname": self.in_h5fname,
            "out_h5fname": self.out_h5fname,
        }
        common_comm.bcast(data, root=0)

        # Send data
        n_samples = inds_arr.shape[0]
        batch_size = self.batch_size
        n_files = int(np.ceil(n_samples / batch_size))
        rankreq = np.empty(1, dtype="i")
        for i in range(n_files):
            st = i * batch_size
            en = st + batch_size
            if en > n_samples:
                en = n_samples
            common_comm.Recv(rankreq, source=MPI.ANY_SOURCE)
            common_comm.Send(inds_arr[st:en].astype(np.int64), tag=i, dest=rankreq[0])
            self.logger.debug(f"Sent {st}:{en} part:{i} to writer {rankreq[0]}")

        self.logger.debug("Done sending")

        # Kill clients
        for i in range(common_comm.Get_size() - 1):
            common_comm.Recv(rankreq, source=MPI.ANY_SOURCE)
            self.logger.debug(f"Kill rank{rankreq[0]}")
            common_comm.Send(bytearray(), dest=rankreq[0])

        # Create virtual dataset
        create_virtual_dataset(self.in_h5fname, self.out_h5fname, n_files)
        self.logger.debug(f"Done joining part files. Output: {self.out_h5fname}")

        common_comm.Barrier()
        common_comm.Abort(1)

    def view(self, n_rows=10):
        # Check the first n_rows timestamps
        """Print the first `n_rows` values of the output file's "timestamp" dataset."""
        chk_f = h5py.File(self.out_h5fname, "r")
        print(f"{chk_f['timestamp'][:n_rows]}")
        chk_f.close()
