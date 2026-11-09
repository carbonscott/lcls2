"""twonode: one hardware-free partition over two hosts of a Slurm job ('daq_sim up --hosts A,B').

'daq_sim up --hosts A,B', run in a Slurm step on host A, starts the partition as procmgr starts one
over several hosts: one .cnf whose entries for host B carry procmgr's host: field.  procmgr starts
B's processes through the procmgrd of the platform there (procServ around /bin/tcsh -f on port
29000 + 100 * platform, as procmgrd.init starts it on a DAQ host), which 'up' starts in a Slurm step
of the same job on B (srun --overlap -w B: the hostd below), and stops them through their procServ
ports.  Host A runs control, the TEB, simxpm, the config DB and run DB stand-ins and the --det DRP
<det>_0; host B runs the other DRPs (<det>_1 .. of --segments, at least 2, and the --also ones).

Addresses: the hosts and their IPs come from the command line (resolved here) and the Slurm job
(SLURM_JOB_ID, SLURM_JOB_NODELIST); nothing else is addressed.  Every EPICS address list names A's
IP only (the PV servers, simxpm and control, run on A); B's processes serve on B's IP.  The ports
are the single-node ones (sim_env.sh: PVA 15075/15076, CA 15064/15065; the platform's block).
libfabric runs over tcp on each host's interface that holds its IP (ep_domain).  The DRPs on B
read simxpm's frames on A's IP and the config DB stand-in there; procmgr writes their logs in the
work dir, which both hosts must share (S3DF: /sdf/data).

    python -m psdaq.sim.twonode hostd -w WORKDIR -p PLATFORM --ip IP --loglink PATH --rcfile RC

hostd (run by 'up' in the step on B) writes <workdir>/hosts/<host>.json ({host, ip, nic, job, step,
pid, ready}), recreates procmgr's log link there, starts procmgrd, and waits until
<workdir>/hosts/<host>.stop exists or it gets SIGTERM; it then kills every process left in its Slurm
step (its cgroup) and writes what it killed and what was left ('stopped') to the same JSON file.
"""

import argparse
import getpass
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

PORTBASE = 29000                         # procmgr's EXECMGRCTRL base (ProcMgr baseport)


def short(host):
    return host.split('.')[0]


def procmgrd_port(platform):
    """procmgr's port for the procmgrd of a platform (ProcMgr.EXECMGRCTRL; procmgrd.init launch1)."""
    return PORTBASE + 100 * int(platform)


def job_nodelist():
    """The node list of this Slurm job's allocation: squeue's for SLURM_JOB_ID (inside a step of a few of the
    job's nodes, SLURM_JOB_NODELIST names only the step's), else SLURM_JOB_NODELIST or SLURM_NODELIST."""
    job = os.environ.get('SLURM_JOB_ID')
    if job:
        try:
            r = subprocess.run(['squeue', '-h', '-j', job, '-o', '%N'], capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            pass
    return os.environ.get('SLURM_JOB_NODELIST') or os.environ.get('SLURM_NODELIST')


def allocated_hosts():
    """Short names of the hosts of this Slurm job's allocation (job_nodelist, expanded by scontrol)."""
    nodelist = job_nodelist()
    if not nodelist:
        return []
    try:
        r = subprocess.run(['scontrol', 'show', 'hostnames', nodelist], capture_output=True, text=True, timeout=30)
        names = r.stdout.split() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    if not names and '[' not in nodelist:
        names = nodelist.split(',')
    return [short(n) for n in names if n]


def ipv4(host):
    """host's IPv4 address (the resolver's); raises OSError if it has none."""
    return socket.gethostbyname(host)


def nic_of(ip):
    """The name of this host's interface that holds ip (ip -o -4 addr), or None."""
    try:
        out = subprocess.run(['ip', '-o', '-4', 'addr', 'show'], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 4 and f[3].split('/')[0] == ip:
            return f[1]
    return None


def check_hosts(hosts, here):
    """(A, B, {A: ip, B: ip}) for --hosts A,B run on `here`, or raise ValueError saying why not: two
    different hosts, this one A, both of this Slurm job's allocation, neither a hutch or DAQ host."""
    names = [h for h in (hosts or '').split(',') if h]
    if len(names) != 2 or short(names[0]) == short(names[1]):
        raise ValueError(f'--hosts HOST_A,HOST_B: two different hosts (given {hosts!r})')
    a, b = names
    for h in names:
        if re.match(r'(drp|daq|mon|ctl|ioc)-', short(h)) or re.search(r'-(daq|drp|mon|control)\b', short(h)):
            raise ValueError(f'refusing {h}: it looks like a hutch or DAQ host')
    if short(here) != short(a):
        raise ValueError(f'run up --hosts on its first host {a} (this is {short(here)}): control, the TEB and '
                         f'the stand-ins run there')
    job, have = os.environ.get('SLURM_JOB_ID'), allocated_hosts()
    if not job:
        raise ValueError('not inside a Slurm job: --hosts needs two hosts of the job this step runs in')
    missing = [h for h in names if short(h) not in have]
    if missing:
        raise ValueError(f'{",".join(missing)} not in Slurm job {job}\'s allocation ({",".join(have) or "none"})')
    ips = {}
    for h in names:
        try:
            ips[h] = ipv4(h)
        except OSError as e:
            raise ValueError(f'cannot resolve {h}: {e}')
    if ips[a] == ips[b] or ips[a].startswith('127.') or ips[b].startswith('127.'):
        raise ValueError(f'the hosts resolve to {ips[a]} and {ips[b]}: want two different node addresses')
    if nic_of(ips[a]) is None:
        raise ValueError(f'{a} resolves to {ips[a]}, which no interface of this host holds')
    return a, b, ips


def epics_env(ip_a, ip_own):
    """The EPICS variables of a process on a host whose IP is ip_own: searches and beacons go to A's IP
    only (the PV servers run on A), unicast, to the ports sim_env.sh sets; a server binds its own IP."""
    return {'EPICS_PVA_AUTO_ADDR_LIST': 'NO', 'EPICS_PVA_ADDR_LIST': ip_a,
            'EPICS_PVAS_INTF_ADDR_LIST': ip_own, 'EPICS_PVAS_BEACON_ADDR_LIST': ip_a,
            'EPICS_PVAS_AUTO_BEACON_ADDR_LIST': 'NO',
            'EPICS_CA_AUTO_ADDR_LIST': 'NO', 'EPICS_CA_ADDR_LIST': ip_a,
            'EPICS_CAS_INTF_ADDR_LIST': ip_own, 'EPICS_CAS_BEACON_ADDR_LIST': ip_a,
            'EPICS_CAS_AUTO_BEACON_ADDR_LIST': 'NO'}


def apply_env(environ, a, b, ips):
    """Set the two-host EPICS lists (epics_env, for A) and NO_PROXY in environ, and the same EPICS values
    in PROCMGR_EXPORT, which procmgr sends (setenv) to the procmgrd on B for each process it starts there."""
    env = epics_env(ips[a], ips[a])
    environ.update(env)
    hosts = {'localhost', '127.0.0.1', a, short(a), b, short(b), ips[a], ips[b]}
    for k in ('NO_PROXY', 'no_proxy'):
        have = [x for x in environ.get(k, '').split(',') if x]
        environ[k] = ','.join(have + sorted(hosts - set(have)))
    items = [x for x in environ.get('PROCMGR_EXPORT', '').split(',') if x and x.split('=', 1)[0] not in env]
    environ['PROCMGR_EXPORT'] = ','.join(items + [f'{k}={v}' for k, v in env.items()])
    return env


def srun_env(environ=None):
    """The environment for srun to start a step of this job on another host: this one less the
    variables of the step it runs in (srun reads them as options)."""
    environ = os.environ if environ is None else environ
    keep = ('SLURM_CONF',)
    return {k: v for k, v in environ.items() if not k.startswith(('SLURM_', 'SRUN_')) or k in keep}


def srun_argv(host, argv, cpus=4, mem='8G'):
    """srun of argv as one task in a new step of this Slurm job on host (--overlap: beside the steps there)."""
    return ['srun', f'--jobid={os.environ["SLURM_JOB_ID"]}', '--overlap', '-w', host, '-N', '1', '--ntasks=1',
            f'--cpus-per-task={cpus}', f'--mem={mem}', '--kill-on-bad-exit=1'] + list(argv)


def run_on(host, argv, timeout=60):
    """(exit code, output) of argv run on host in a step of this job."""
    try:
        r = subprocess.run(srun_argv(host, argv, cpus=1, mem='1G'), capture_output=True, text=True,
                           timeout=timeout, env=srun_env(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, f'timed out after {timeout} s'
    return r.returncode, r.stdout + r.stderr


def info_path(workdir, host):
    return os.path.join(workdir, 'hosts', f'{short(host)}.json')


def read_info(workdir, host):
    try:
        with open(info_path(workdir, host)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def start_hostd(work, state, host, ip, loglink, rcfile, log):
    """Start hostd on host in a new step of this job; returns the srun Popen (its client runs here)."""
    os.makedirs(work.path('hosts'), exist_ok=True)
    for p in (info_path(work.dir, host), info_path(work.dir, host)[:-5] + '.stop'):
        if os.path.exists(p):
            os.unlink(p)
    argv = [sys.executable, '-m', 'psdaq.sim.twonode', 'hostd', '-w', work.dir, '-p', str(state['platform']),
            '--ip', ip, '--loglink', loglink, '--rcfile', rcfile]
    out = open(log, 'ab')
    return subprocess.Popen(srun_argv(host, argv), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env=srun_env(), cwd=work.dir, start_new_session=True)


def wait_hostd(work, host, proc, timeout=180):
    """hostd's info once it says ready (procmgrd listens), or raise RuntimeError."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        info = read_info(work.dir, host)
        if info and info.get('ready'):
            return info
        if info and info.get('error'):
            raise RuntimeError(f'hostd on {host}: {info["error"]}')
        if proc.poll() is not None:
            raise RuntimeError(f'hostd step on {host} ended (srun exit {proc.returncode}) before procmgrd was ready')
        time.sleep(0.5)
    raise RuntimeError(f'hostd on {host} not ready after {timeout} s')


def stop_hostd(work, state, say):
    """Have each hostd kill what is left in its step and end it; True if every step ended with nothing left.
    A step that does not end within 60 s is cancelled (scancel <job>.<step>)."""
    ok = True
    for host, h in (state.get('hostd') or {}).items():
        open(info_path(work.dir, host)[:-5] + '.stop', 'w').close()
        end = time.monotonic() + 60
        while time.monotonic() < end and _alive(h.get('srun_pid')):
            time.sleep(0.5)
        info = read_info(work.dir, host) or {}
        step = info.get('step')
        if _alive(h.get('srun_pid')):
            ok = False
            if step is not None:
                subprocess.run(['scancel', f'{info.get("job")}.{step}'], capture_output=True, timeout=60)
            say(f'hostd on {host} (step {step}) did not end: cancelled the step')
        stopped = info.get('stopped') or {}
        left = stopped.get('left')
        if left:
            ok = False
        say(f'hostd on {host}: step {info.get("job")}.{step} ended; killed {len(stopped.get("killed") or [])} '
            f'process(es) of the step ({", ".join(stopped.get("killed") or []) or "none"}), left '
            f'{left if left is not None else "unknown"}')
        if left is None:
            ok = False
    return ok


def _alive(pid):
    if not pid:
        return False
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().rsplit(')', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        return False


def established(peer_ip, here_ip, lines):
    """The established TCP connections between here_ip and peer_ip in 'ss -tnpH state established' lines:
    [(local, peer, owners)], owners as ss prints them (users:(("name",pid=N,fd=M)))."""
    def host(addr):                     # 1.2.3.4:5, [::ffff:1.2.3.4]:5 -> 1.2.3.4
        h = addr.rsplit(':', 1)[0].strip('[]')
        return h[len('::ffff:'):] if h.startswith('::ffff:') else h
    out = []
    for line in lines:
        f = line.split()
        k = [i for i, x in enumerate(f) if re.search(r':\d+$', x)][:2]     # local and peer address:port
        if len(k) == 2 and host(f[k[0]]) == here_ip and host(f[k[1]]) == peer_ip:
            out.append((f[k[0]], f[k[1]], ' '.join(f[k[1] + 1:])))
    return out


def ss_lines(host=None):
    """'ss -tnpH state established' output lines, here or (host) in a step of this job there."""
    argv = ['ss', '-tnpH', 'state', 'established']
    if host is None:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return r.stdout.splitlines()
    rc, out = run_on(host, argv)
    return out.splitlines() if rc == 0 else [f'ss on {host} failed: {out.strip()[-200:]}']


def kill_on(host, pid):
    """SIGKILL pid on host (a step of this job there: the user's own process)."""
    return run_on(host, ['kill', '-9', str(pid)])


# --- hostd: runs on host B in its own step ---------------------------------------------------

def _cgroup_procs():
    """The pids of this process's cgroup (v2: /proc/self/cgroup '0::<path>'), its Slurm step's processes."""
    try:
        with open('/proc/self/cgroup') as f:
            path = [l.strip().split(':', 2)[2] for l in f if l.startswith('0::')][0]
        with open(os.path.join('/sys/fs/cgroup', path.lstrip('/'), 'cgroup.procs')) as f:
            return [int(x) for x in f.read().split()]
    except (OSError, IndexError, ValueError):
        return None


def _cmd(pid):
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().replace(b'\0', b' ').decode(errors='replace').strip()[:120]
    except OSError:
        return '?'


def hostd(args):
    host = socket.gethostname()
    path = info_path(args.workdir, host)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    info = {'host': host, 'ip': args.ip, 'nic': nic_of(args.ip), 'job': os.environ.get('SLURM_JOB_ID'),
            'step': os.environ.get('SLURM_STEP_ID'), 'pid': os.getpid(), 'ready': False}

    def save():
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(info, f, indent=1)
        os.replace(tmp, path)
    if info['nic'] is None:
        info['error'] = f'no interface of {host} holds {args.ip}'
        save()
        return 1
    pmlogs = os.path.join(args.workdir, 'pmlogs')
    if args.loglink != pmlogs:                # 'up' links a short path to <workdir>/pmlogs (procmgr -o <= 50 chars)
        if os.path.islink(args.loglink):
            os.unlink(args.loglink)
        if os.path.exists(args.loglink):
            info['error'] = f'{args.loglink} exists and is not a link'
            save()
            return 1
        os.symlink(pmlogs, args.loglink)
    procserv = None
    with open(args.rcfile) as f:
        for line in f:
            m = re.match(r'\s*PROCSERVBIN=(\S+)', line)
            if m:
                procserv = m.group(1)
    port = procmgrd_port(args.platform)
    argv = [procserv, '--allow', '--ignore', '^D', '-l', str(port + 1), '--coresize', '0', '-c', '/tmp',
            '--name', f'procmgrd{args.platform}', str(port), '/bin/tcsh', '-f']
    info['procmgrd'] = ' '.join(argv)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)     # procServ forks into the background
    if r.returncode != 0:
        info['error'] = f'procmgrd: {" ".join(argv)} exited {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}'
        save()
        return 1
    end = time.monotonic() + 30
    while time.monotonic() < end:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        info['error'] = f'procmgrd not listening on {port} after 30 s'
        save()
        return 1
    info['ready'] = True
    save()
    print(f'hostd {host}: job {info["job"]} step {info["step"]}: procmgrd{args.platform} on port {port} '
          f'({args.ip}, {info["nic"]}); waiting for {path[:-5]}.stop', flush=True)
    stop = [False]
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *a: stop.__setitem__(0, True))
    while not stop[0] and not os.path.exists(path[:-5] + '.stop'):
        time.sleep(0.5)
    killed = []
    for _ in range(3):                    # everything procmgrd started, in this step's cgroup
        procs = [p for p in (_cgroup_procs() or []) if p != os.getpid()]
        for p in procs:
            c = _cmd(p)
            try:
                os.kill(p, signal.SIGKILL)
                killed.append(f'{p} {c.split(" ")[0].rsplit("/", 1)[-1]}')
            except OSError:
                pass
        time.sleep(1)
    left = [f'{p} {_cmd(p)}' for p in (_cgroup_procs() or []) if p != os.getpid()]
    if args.loglink != pmlogs and os.path.islink(args.loglink) and os.readlink(args.loglink) == pmlogs:
        os.unlink(args.loglink)
    info['stopped'] = {'killed': sorted(set(killed)), 'left': len(left), 'left_procs': left}
    save()
    print(f'hostd {host}: stopped; killed {len(set(killed))}, left {len(left)}', flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m psdaq.sim.twonode', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    h = sub.add_parser('hostd', help='run on host B in a step of the job: procmgrd for procmgr there')
    h.add_argument('-w', '--workdir', required=True)
    h.add_argument('-p', '--platform', type=int, required=True)
    h.add_argument('--ip', required=True, help='this host\'s IP the partition uses')
    h.add_argument('--loglink', required=True, help='procmgr\'s -o log path (a link to <workdir>/pmlogs)')
    h.add_argument('--rcfile', required=True, help='procmgr\'s rcfile (PROCSERVBIN)')
    args = ap.parse_args(argv)
    return hostd(args)


if __name__ == '__main__':
    sys.exit(main())
