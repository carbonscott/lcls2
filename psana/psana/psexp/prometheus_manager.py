"""Prometheus monitoring helpers for psana.

Provides a process-wide `PrometheusManager` that holds the psana metrics registry, a background
thread that pushes the metrics to a push gateway, and an HTTP exposer. The push gateway is
https://172.24.5.157:9091 on hosts whose name starts with "sdf", otherwise psdm03:9091.
"""
import getpass
import os
import socket
import time
from subprocess import Popen
import threading

from prometheus_client import (CollectorRegistry, Counter, Gauge, Summary,
                               push_to_gateway, start_http_server)
from prometheus_client.exposition import tls_auth_handler

from psana.psexp.tools import mode

if mode == "mpi":
    from mpi4py import MPI
    size = MPI.COMM_WORLD.Get_size()
else:
    size = 1

PUSH_INTERVAL_SECS = 5

if socket.gethostname().startswith("sdf"):
    PUSH_GATEWAY = "https://172.24.5.157:9091"
else:
    PUSH_GATEWAY = "psdm03:9091"

PROM_PORT_BASE = 9200  # Used by the http exposer; Value should match DAQ's

HTTP_EXPOSER_STARTED = False


_singleton = None
_singleton_lock = threading.Lock()
_pusher_event = None
_pusher_thread = None

def get_prom_manager(job=None):
    """Return the process-wide PrometheusManager instance."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = PrometheusManager(job=job)
        elif job and _singleton.job != job:
            # Optional: update job on first mismatch, or warn
            _singleton.job = job
        return _singleton

def ensure_pusher(rank=0):
    """Start exactly one push loop in this process. Safe to call many times."""
    global _pusher_event, _pusher_thread
    pm = get_prom_manager()
    pm.set_rank(rank)
    if _pusher_thread is None or not _pusher_thread.is_alive():
        _pusher_event = threading.Event()
        _pusher_thread = threading.Thread(
            name=f"PrometheusThread{rank}",
            target=pm.push_metrics,  # uses the event to stop
            args=(_pusher_event,),
            daemon=True,
        )
        _pusher_thread.start()
    return pm

def stop_pusher():
    """Stop the background push thread started by `ensure_pusher`.

    Sets the stop event, waits up to 2 seconds for the thread (errors are ignored), and clears the
    module-level event and thread references.
    """
    global _pusher_event, _pusher_thread
    if _pusher_event:
        _pusher_event.set()
    if _pusher_thread:
        try:
            _pusher_thread.join(timeout=2)
        except Exception:
            pass
    _pusher_event = None
    _pusher_thread = None


def createExposer(prometheusCfgDir):
    """Start a Prometheus HTTP metrics server on the first free port from 9200 to 9299.

    Also writes the target file `<prometheusCfgDir>/drpmon_<hostname>_<port - 9200>.yaml` if it
    does not exist. Only one server is started per process.

    Returns
    -------
    bool or None
        True on success; False if no port is free or the file cannot be written; None if
        `prometheusCfgDir` is "" (a message is printed) or a server was already started.
    """
    if prometheusCfgDir == "":
        print(
            "Unable to update Prometheus configuration: directory not provided"
        )
        return

    # Start only one server per session to avoid multiple scrapings per time point
    global HTTP_EXPOSER_STARTED
    if HTTP_EXPOSER_STARTED:
        return

    hostname = socket.gethostname()
    port = PROM_PORT_BASE
    while port < PROM_PORT_BASE + 100:
        try:
            start_http_server(port)
            fileName = (
                f"{prometheusCfgDir}/drpmon_{hostname}_{port - PROM_PORT_BASE}.yaml"
            )
            if not os.path.exists(fileName):
                try:
                    with open(fileName, "wt") as f:
                        f.write(f"- targets:\n    - {hostname}:{port}\n")
                except Exception as ex:
                    print(f"Error creating file {fileName}: {ex}")
                    return False
            else:
                pass  # File exists; no need to rewrite it
            print(f"Providing run-time monitoring data on port {port}")
            HTTP_EXPOSER_STARTED = True
            return True
        except OSError:
            pass  # Port in use
        port += 1
    print("No available port found for providing run-time monitoring")
    return False


def my_auth_handler(url, method, timeout, headers, data):
    # TODO Certificate and key files are hard-coded
    """Push-gateway handler that adds TLS client authentication.

    Passes all arguments to `prometheus_client.exposition.tls_auth_handler` together with the
    hard-coded certificate `/sdf/group/lcls/ds/ana/data/prom/promgwclient.pem` and key
    `/sdf/group/lcls/ds/ana/data/prom/promgwclient.key`, with `insecure_skip_verify=True`, and
    returns its result.
    """
    certfile = "/sdf/group/lcls/ds/ana/data/prom/promgwclient.pem"
    keyfile = "/sdf/group/lcls/ds/ana/data/prom/promgwclient.key"
    return tls_auth_handler(
        url,
        method,
        timeout,
        headers,
        data,
        certfile,
        keyfile,
        insecure_skip_verify=True,
    )


class PrometheusManager(object):
    """Manage the psana Prometheus metrics.

    `registry` (a `CollectorRegistry`) and `metrics` (the table of known metric names with their
    type, description and label names) are class attributes shared by all instances. An instance
    stores the user name, a rank (default 0) and the job name: `job`, else the environment variable
    SLURM_JOB_ID, else the user name.
    """
    registry = CollectorRegistry()
    # Store available psana metrics by metric_type, description, and labelnames
    metrics = {
        "psana_smd0_read": ("Gauge", "Disk reading rate (MB/s) for smd0", ()),
        "psana_smd0_rate": ("Gauge", "Processing rate by smd0 (kHz)", ()),
        "psana_smd0_wait": ("Gauge", "time Smd0 spent (s) waiting for Eb cores", ()),
        "psana_eb_rate": ("Gauge", "Processing rate by eb (kHz)", ()),
        "psana_eb_wait_smd0": ("Gauge", "time Eb spent (s) waiting for Smd0", ()),
        "psana_eb_wait_bd": ("Gauge", "time Eb spent (s) waiting for Bd cores", ()),
        "psana_bd_rate": ("Gauge", "Processing rate by bd (kHz)", ()),
        "psana_bd_read": ("Gauge", "Disk reading rate (MB/s) for bd", ()),
        "psana_bd_ana_rate": ("Gauge", "User-analysis rate on bd (Hz)", ()),
        "psana_bd_wait": ("Gauge", "time spent (s) waiting for its Eb", ()),
        "psana_srv_wait": ("Gauge", "time Srv spent (s) waiting for Bd cores", ()),
        "psana_srv_rate": ("Gauge", "Processing rate by srv (kHz)", ()),
    }
    def __init__(self, job=None):
        self.username = getpass.getuser()
        self.rank = 0
        if job is None:
            default_job_id = os.environ.get("SLURM_JOB_ID", f"{self.username}")
            self.job = default_job_id
        else:
            self.job = job

    def set_rank(self, rank):
        """Set the rank used as the "rank" grouping key when pushing metrics."""
        self.rank = rank

    def register(self, metric_name):
        """Register `metric_name` with the shared registry.

        The argument is passed unchanged to `CollectorRegistry.register`.
        """
        self.registry.register(metric_name)

    def push_metrics(self, e):
        # TODO: Certificate is read at every push, find a better way.
        """Push the registry to the push gateway every 5 seconds until event `e` is set.

        Uses job `self.job` and grouping key {"rank": self.rank}. On hosts whose name starts with "sdf"
        the push uses `my_auth_handler` for TLS client authentication.
        """
        while not e.isSet():
            if socket.gethostname().startswith("sdf"):
                push_to_gateway(
                    PUSH_GATEWAY,
                    job=self.job,
                    grouping_key={"rank": self.rank},
                    registry=self.registry,
                    handler=my_auth_handler,
                    timeout=None,
                )
            else:
                push_to_gateway(
                    PUSH_GATEWAY,
                    job=self.job,
                    grouping_key={"rank": self.rank},
                    registry=self.registry,
                    timeout=None,
                )
            time.sleep(PUSH_INTERVAL_SECS)

    def delete_all_metrics_on_pushgateway(self, n_ranks=0):
        """Delete this job's metric groups from the push gateway for ranks 0 to `n_ranks` - 1.

        Starts one `curl -k -X DELETE <gateway>/metrics/job/<job>/rank/<i>` subprocess per rank and
        does not wait for them. `n_ranks` = 0 means the MPI world size (1 when not in MPI mode).
        """
        if not n_ranks:
            n_ranks = size
        for i_rank in range(n_ranks):
            args = [
                "curl",
                "-k",
                "-X",
                "DELETE",
                f"{PUSH_GATEWAY}/metrics/job/{self.job}/rank/{i_rank}",
            ]
            Popen(args)

    def create_exposer(self, prometheus_cfg_dir):
        """Call `createExposer(prometheus_cfg_dir)` and return its result."""
        return createExposer(prometheus_cfg_dir)

    def create_metric(self, metric_name):
        """Create the metric `metric_name` from the class `metrics` table and register it.

        The type (Counter, Summary or Gauge), description and label names come from the table. Names
        not in the table only print a warning.
        """
        if metric_name in self.metrics:
            metric_type, desc, labelnames = self.metrics[metric_name]
            if metric_type == "Counter":
                self.registry.register(Counter(metric_name, desc, labelnames))
            elif metric_type == "Summary":
                self.registry.register(Summary(metric_name, desc, labelnames))
            elif metric_type == "Gauge":
                self.registry.register(Gauge(metric_name, desc, labelnames))
        else:
            print(
                f"Warning: {metric_name} is not found in the list of available prometheus metrics"
            )

    def get_metric(self, metric_name):
        # get metric object from its name
        # NOTE that _created has to be appended to locate the key
        """Return the registered collector for `metric_name`.

        If it is not registered yet it is created with `create_metric` first. The lookup uses the
        registry's private `_names_to_collectors`, so a name not in the `metrics` table raises KeyError.
        """
        if metric_name in self.registry._names_to_collectors:
            collector = self.registry._names_to_collectors[metric_name]
        else:
            self.create_metric(metric_name)
            collector = self.registry._names_to_collectors[metric_name]
        return collector
