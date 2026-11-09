"""simslurm: a stand-in for the Slurm commands daqmgr (psdaq/slurm) runs, so daqstat shows job states with no Slurm.

The jobs live in a JSON state file (locked while read and written).  run(argv, state) answers the commands
psdaq.slurm.utils / psdaq.slurm.main issue, in their output formats:
  squeue -u USER -h -o FMT            one line per active job, FMT's %i %k %j %T %R filled (the quotes kept)
  squeue --noheader --jobs IDS --format=%i|%T
  sacct -u USER -n --format=...       every job, active or ended: id comment name state nodelist
  scontrol show job ID                JobId= ... StdOut=<its log file>
  sbatch FILE                         a new PENDING job from FILE's #SBATCH --job-name/--comment/--output/--nodelist
  scancel IDS                         the jobs end CANCELLED
  sinfo -N -h -o "%N %f"              this host, no features
Any other command is refused (exit 127).  Nothing here talks to a Slurm controller or starts a job.

As a device (python -m psdaq.sim.simslurm --state FILE --cnf CNF --logdir DIR) it seeds one job per process of the
daqmgr .cnf as `daqmgr start` would have submitted it (comment x<xpm>_p<platform>_s<station>_<id>, from
psdaq.slurm.main.Runner's own parsing of CNF), every third PENDING and the rest RUNNING, each with a log file under
DIR; then, once a second, a job PENDING for 3 s starts RUNNING and every RUNNING job's log gets a line.  It prints a
'ready' line and stays up until terminated; its pid is in the state file.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
import time

ACTIVE = ('PENDING', 'RUNNING', 'SUSPENDED', 'COMPLETING')


@contextlib.contextmanager
def locked(path):
    with open(path + '.lock', 'a') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(path) as f:
                st = json.load(f)
        except FileNotFoundError:
            st = {'jobs': [], 'next_id': 9100001, 'commands': 0}
        yield st
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, path)


def _fmt(fmt, j):
    return fmt.replace('%i', str(j['job_id'])).replace('%k', j['comment']).replace('%j', j['job_name']) \
              .replace('%T', j['state']).replace('%R', j['nodelist'])


def _opt(argv, name):
    for k, a in enumerate(argv):
        if a == name and k + 1 < len(argv):
            return argv[k + 1]
        if a.startswith(name + '='):
            return a.split('=', 1)[1]
    return None


def run(argv, state, stdin=None):
    """(returncode, stdout, stderr) of Slurm command argv against the jobs of state file `state`."""
    cmd = os.path.basename(argv[0]) if argv else ''
    with locked(state) as st:
        st['commands'] = st.get('commands', 0) + 1
        jobs = st['jobs']
        if cmd == 'squeue':
            ids = _opt(argv, '--jobs')
            fmt = _opt(argv, '-o') or _opt(argv, '--format') or '%i %T'
            sel = [j for j in jobs if j['state'] in ACTIVE and (ids is None or str(j['job_id']) in ids.split(','))]
            return 0, ''.join(_fmt(fmt, j) + '\n' for j in sel), ''
        if cmd == 'sacct':
            return 0, ''.join('%12s %30s %10s %10s %s\n' % (j['job_id'], j['comment'], j['job_name'], j['state'],
                                                           j['nodelist']) for j in jobs), ''
        if cmd == 'scontrol' and argv[1:3] == ['show', 'job'] and len(argv) > 3:
            j = next((j for j in jobs if str(j['job_id']) == argv[3]), None)
            if j is None:
                return 1, '', 'slurm_load_jobs error: Invalid job id specified\n'
            return 0, ('JobId=%s JobName=%s\n   JobState=%s Reason=None\n   Comment=%s\n   NodeList=%s\n'
                       '   StdOut=%s\n' % (j['job_id'], j['job_name'], j['state'], j['comment'], j['nodelist'],
                                           j['logfile'])), ''
        if cmd == 'sbatch' and len(argv) > 1:
            with open(argv[-1]) as f:
                script = f.read()
            opts = dict(re.findall(r'^#SBATCH --([a-z-]+)=(\S+)', script, re.M))
            jid = st['next_id']
            st['next_id'] += 1
            j = {'job_id': jid, 'job_name': opts.get('job-name', 'job'), 'comment': opts.get('comment', ''),
                 'nodelist': opts.get('nodelist', 'localhost'), 'state': 'PENDING', 'since': time.time(),
                 'logfile': opts.get('output', ''), 'submitted_by': 'sbatch'}
            jobs.append(j)
            return 0, 'Submitted batch job %d\n' % jid, ''
        if cmd == 'scancel':
            n = 0
            for j in jobs:
                if str(j['job_id']) in argv[1:] and j['state'] in ACTIVE:
                    j['state'], j['since'] = 'CANCELLED', time.time()
                    n += 1
            return 0, '', ''
        if cmd == 'sinfo':
            return 0, '"localhost "\n', ''
    return 127, '', 'simslurm: %s is not a Slurm command simslurm answers\n' % cmd


def seed(state, cnf, logdir):
    from psdaq.slurm import utils as U
    from psdaq.slurm.main import Runner
    U.subprocess = SubprocessStandIn(state)
    r = Runner(cnf, output=logdir)
    os.makedirs(logdir, exist_ok=True)
    with locked(state) as st:
        st.update({'pid': os.getpid(), 'cnf': os.path.abspath(cnf), 'logdir': os.path.abspath(logdir), 'jobs': [],
                   'next_id': 9100001, 'commands': 0, 'prefix': r.get_unique_prefix()})
        for k, (cid, d) in enumerate(r.config.items()):
            jid = st['next_id']
            st['next_id'] += 1
            log = os.path.join(logdir, '%d_%s.log' % (jid, cid))
            with open(log, 'w') as f:
                f.write('simslurm: job %d %s started for %s\n%s\n' % (jid, cid, cnf, d.get('cmd', '')))
            st['jobs'].append({'job_id': jid, 'job_name': cid, 'comment': r.sbman.get_comment(cid),
                               'nodelist': d.get('host', 'localhost'), 'state': 'PENDING' if k % 3 == 2 else 'RUNNING',
                               'since': time.time(), 'logfile': log, 'submitted_by': 'seed'})
        return [j['job_name'] for j in st['jobs']]


def tick(state, n):
    with locked(state) as st:
        for j in st['jobs']:
            if j['state'] == 'PENDING' and time.time() - j['since'] > 3:
                j['state'], j['since'] = 'RUNNING', time.time()
            if j['state'] == 'RUNNING' and j.get('logfile'):
                with open(j['logfile'], 'a') as f:
                    f.write('simslurm: %s tick %d\n' % (j['job_name'], n))


class _Completed:
    def __init__(self, args, rc, out, err):
        self.args, self.returncode, self.stdout, self.stderr = args, rc, out, err


class SubprocessStandIn:
    """The `subprocess` psdaq.slurm.utils sees: Slurm commands are answered by simslurm, anything else refused."""

    def __init__(self, state):
        import subprocess
        self.state = state
        self.PIPE, self.DEVNULL = subprocess.PIPE, subprocess.DEVNULL
        self.CalledProcessError, self.TimeoutExpired = subprocess.CalledProcessError, subprocess.TimeoutExpired

    def run(self, args, text=False, check=False, capture_output=False, stdout=None, stderr=None, **k):
        rc, out, err = run(list(args), self.state)
        if not text:
            out, err = out.encode(), err.encode()
        if check and rc != 0:
            raise self.CalledProcessError(rc, args, out, err)
        return _Completed(args, rc, out, err)

    def check_output(self, args, stderr=None, **k):
        rc, out, err = run(list(args), self.state)
        if rc != 0:
            raise self.CalledProcessError(rc, args, out.encode(), err.encode())
        return out.encode()


class ProcStandIn:
    """psdaq.slurm.subproc.SubprocHelper for Runner.submit: sbatch answered by simslurm."""

    def __init__(self, state):
        self.state = state

    async def run_exec(self, args, env=None, echo_output=True):
        rc, out, err = run(list(args), self.state)
        if rc != 0 or echo_output:
            sys.stdout.write(out)
            sys.stderr.write(err)
        return rc


def main():
    ap = argparse.ArgumentParser(description='a Slurm stand-in for daqmgr / daqstat (no Slurm controller)')
    ap.add_argument('--state', required=True, help='job state file (made)')
    ap.add_argument('--cnf', required=True, help='the daqmgr config (.py) whose processes get jobs, or a procmgr .cnf, '
                                                 'converted to --py by daqmgr\'s own psdaq.slurm.cnftopy')
    ap.add_argument('--py', help='where to write the daqmgr config converted from a .cnf (default: next to --state)')
    ap.add_argument('--logdir', required=True, help='directory for the job log files')
    a = ap.parse_args()
    cnf = a.cnf
    if cnf.endswith('.cnf'):
        from psdaq.slurm.cnftopy import main as cnftopy
        cnf = a.py or os.path.join(os.path.dirname(os.path.abspath(a.state)), 'daqstat.py')
        os.makedirs(os.path.dirname(os.path.abspath(cnf)), exist_ok=True)
        with contextlib.redirect_stdout(sys.stderr):
            cnftopy(a.cnf, cnf)
    ids = seed(a.state, cnf, a.logdir)
    print('simslurm: ready, %d jobs (%s) in %s, pid %d' % (len(ids), ' '.join(ids), a.state, os.getpid()), flush=True)
    n = 0
    while True:
        time.sleep(1.0)
        n += 1
        tick(a.state, n)


if __name__ == '__main__':
    sys.exit(main())
