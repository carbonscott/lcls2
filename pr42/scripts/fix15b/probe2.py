# probe2.py: what one 8240-byte loopback datagram costs a receive buffer (/proc/net/udp rx_queue per queued packet),
# and how many queue at a 16 MiB-request socket before the kernel drops (rx_queue, drops)
import socket, struct
def q(port):
    key = '0100007F:%04X' % port
    for line in open('/proc/net/udp'):
        f = line.split()
        if f[1] == key:
            return int(f[4].split(':')[1], 16), int(f[-1])
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 << 20)
rx.bind(('127.0.0.1', 0)); port = rx.getsockname()[1]; buf = rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for n in (1, 10):
    for _ in range(n if n == 1 else n - 1):
        tx.sendto(b'x' * 8240, ('127.0.0.1', port))
    print(f'{socket.gethostname()}: rcvbuf {buf} B; {n} queued: rx_queue, drops = {q(port)}; per packet {q(port)[0] // n} B')
for _ in range(200):
    tx.sendto(b'x' * 8240, ('127.0.0.1', port))
print(f'after 210 sent: rx_queue, drops = {q(port)}')
