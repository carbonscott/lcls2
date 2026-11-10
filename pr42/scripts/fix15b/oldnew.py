"""oldnew.py REV...: test_one_frame_per_trigger's slow case (frames through a 256 KiB receive buffer, read at 1 ms per
packet) with simsls' Module from each REV (git show, 'HEAD' = this checkout's commit), driven directly (no TCP): how many
of each frame's 128 packets arrive, and the receiving socket's drops (/proc/net/udp)."""
import socket, struct, subprocess, sys, time, types
def load(rev):
    src = subprocess.check_output(['git', 'show', f'{rev}:psdaq/psdaq/sim/simsls.py'], text=True)
    m = types.ModuleType(f'simsls_{rev}')
    exec(compile(src, f'simsls.py@{rev}', 'exec'), m.__dict__)
    return m
def drops(port):
    for line in open('/proc/net/udp'):
        c = line.split()
        if c[1] == '0100007F:%04X' % port:
            return int(c[4].split(':')[1], 16), int(c[-1])
for rev in sys.argv[1:]:
    S = load(rev)
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 128 << 10)
    rx.bind(('127.0.0.1', 0)); rx.settimeout(1.0)
    buf, port = rx.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF), rx.getsockname()[1]
    m = S.Module(seed=0x1234)
    if hasattr(m, 'rcvbuf'):
        m.rcvbuf = buf
    lo = struct.unpack('<I', socket.inet_aton('127.0.0.1'))[0]
    m.src_ip = m.dst_ip = lo; m.src_mac = m.dst_mac = 1; m.dst_port = port; m.power = 1
    m.timing, m.frames, m.triggers = S.TRIGGER_EXPOSURE, 1, 100
    m.start_acquisition()
    got = []
    for frame in (1, 2, 3):
        m.trigger()
        n = 0
        try:
            while n < 128:
                rx.recv(9000); n += 1
                time.sleep(0.001)
        except socket.timeout:
            pass
        got.append(n)
    m.stop_acquisition()
    print(f'simsls at {rev}: receive buffer {buf} B, read at 1 ms per packet: packets of frames 1, 2, 3: {got}; '
          f'the socket\'s (queue, drops) {drops(port)}; module counts {m.counts}', flush=True)
    rx.close()
