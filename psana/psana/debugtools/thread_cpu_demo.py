"""Script: start 60 threads that each query the CPU number 100 times and print it once with the process id; all of this runs at import time.

The CPU query is ``os.sched_getcpu`` when available.
"""
import threading
import os

print(f"Start thread_cpu_demo pid: {os.getpid()}")
def get_cpu():
    """Return ``psutil.Process().cpu_num()``.

    At import the name ``get_cpu`` is rebound to ``os.sched_getcpu`` if it exists; otherwise it is rebound to the integer returned by one call of this function, so the later calls in ``worker`` would fail.
    """
    import psutil
    return psutil.Process().cpu_num()

try:
    get_cpu = os.sched_getcpu  # Python 3.8+ only on Linux
except AttributeError:
    get_cpu = get_cpu()

def worker(thread_id):
    """Call ``get_cpu()`` 100 times and print the thread id, the CPU number of the first call and the process id."""
    for _ in range(100):
        cpu = get_cpu()
        if _  == 0:
            print(f"Thread {thread_id:02d} running on CPU {cpu} pid: {os.getpid()}")

threads = []

for i in range(60):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()


