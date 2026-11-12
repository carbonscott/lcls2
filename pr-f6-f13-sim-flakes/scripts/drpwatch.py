#!/usr/bin/env python3
"""drpwatch.py WDPREFIX PROG DET MODE SECS DELAY DONEFILE: act on one DRP from outside (no hook in the code).

Matches only processes of this uid whose environment holds DAQ_SIM_WORKDIR=<WDPREFIX...> (the tag 'daq_sim up'
puts on every process it starts) and whose argv[0] basename is PROG, with '-D DET' in argv unless DET is '-'.
Only the first such process is touched.
MODE stop  SIGSTOP DELAY s after first seen, SIGCONT SECS s after the STOP
     hang  SIGSTOP DELAY s after first seen, never SIGCONT while the run lasts (SIGCONT at the end if alive)
     kill  SIGKILL DELAY s after first seen
     stopkill  SIGSTOP at once (it never gets to 'Ready for transitions'), SIGKILL DELAY s after first seen
Runs until DONEFILE exists (the driver touches it when the matrix ends).  Logs every action with the pid,
its process state from /proc and its command line.
"""
import os, signal, sys, time

wd, prog, det, mode, secs, delay, done = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]), float(sys.argv[6]), sys.argv[7]
uid = os.getuid()
tag = f'DAQ_SIM_WORKDIR={wd}'.encode()

def ts():
    t = time.time(); return time.strftime('%H:%M:%S', time.localtime(t)) + f'.{int(t % 1 * 1000):03d}'

def log(*a):
    print(ts(), *a, flush=True)

def read(pid, name):
    try:
        with open(f'/proc/{pid}/{name}', 'rb') as f:
            return f.read()
    except OSError:
        return None

def state(pid):
    s = read(pid, 'stat')
    return s.decode().rsplit(')', 1)[1].split()[0] if s else 'gone'

def match(pid):
    try:
        if os.stat(f'/proc/{pid}').st_uid != uid:
            return None
    except OSError:
        return None
    c = read(pid, 'cmdline')
    if not c:
        return None
    a = [x.decode(errors='replace') for x in c.split(b'\0')[:-1]]
    if not a or os.path.basename(a[0]) != prog:
        return None
    if det != '-' and not any(a[i] == '-D' and a[i + 1] == det for i in range(len(a) - 1)):
        return None
    e = read(pid, 'environ') or b''
    if not any(v.startswith(tag) for v in e.split(b'\0')):
        return None
    return a

log(f'drpwatch wd={wd} prog={prog} det={det} mode={mode} secs={secs} delay={delay} uid={uid} host={os.uname().nodename}')
pid = None; seen = stopped = None; acted = False
while not os.path.exists(done):
    now = time.monotonic()
    if pid is None:
        for p in os.listdir('/proc'):
            if p.isdigit():
                a = match(int(p))
                if a:
                    pid, seen = int(p), now
                    log(f'SEEN pid {pid} state {state(pid)}: {" ".join(a)[:300]}')
                    break
    elif mode == 'stopkill' and stopped is None and not acted:
        try:
            os.kill(pid, signal.SIGSTOP); stopped = now
            time.sleep(0.05); log(f'STOP pid {pid} {now - seen:.1f} s after first seen, state {state(pid)}')
        except ProcessLookupError:
            log(f'pid {pid} gone before STOP')
    elif not acted and now - seen >= delay:
        acted = True
        if mode in ('kill', 'stopkill'):
            stopped = None
            try:
                os.kill(pid, signal.SIGKILL); log(f'KILL pid {pid} {now - seen:.1f} s after first seen')
            except ProcessLookupError:
                log(f'pid {pid} gone before KILL')
        else:
            try:
                os.kill(pid, signal.SIGSTOP); stopped = now
                time.sleep(0.05); log(f'STOP pid {pid} {now - seen:.1f} s after first seen, state {state(pid)}')
            except ProcessLookupError:
                log(f'pid {pid} gone before STOP')
    elif stopped is not None and mode == 'stop' and now - stopped >= secs:
        try:
            os.kill(pid, signal.SIGCONT); log(f'CONT pid {pid} after {now - stopped:.1f} s stopped ({now - seen:.1f} s after first seen), state {state(pid)}')
        except ProcessLookupError:
            log(f'pid {pid} gone before CONT ({now - stopped:.1f} s after STOP)')
        stopped = None
    time.sleep(0.1)
if pid is None:
    log('NEVER SEEN')
elif stopped is not None:
    st = state(pid)
    if st != 'gone':
        os.kill(pid, signal.SIGCONT); log(f'end: CONT pid {pid} (state was {st}) {time.monotonic() - stopped:.1f} s after STOP')
    else:
        log(f'end: pid {pid} gone, {time.monotonic() - stopped:.1f} s after STOP')
log('drpwatch done')
