# probe.py: cost of one /proc/net/udp read, its line count, and the receive buffer a 16 MiB SO_RCVBUF request gets
import socket, time
t = time.perf_counter(); n = 0
for _ in range(200):
    with open('/proc/net/udp') as f:
        n = len(f.read().splitlines())
dt = (time.perf_counter() - t) / 200
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 << 20)
print(f'{socket.gethostname()}: /proc/net/udp {n} lines, {dt*1e6:.0f} us per read; SO_RCVBUF 16 MiB request gets {s.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)} B; rmem_max {open("/proc/sys/net/core/rmem_max").read().strip()}')
