"""Run an agent on eval cases and keep what grade.py needs.

    python3 run.py --work WORK_DIR --arm NAME --skills SKILLS_DIR|none --out RESULTS_DIR
                   [--set core|full] [--case ID ...] [--repeats N] [--jobs N] [--model M]
                   [--preface TEXT] [--expose DIR] [--resume] [--dry-run] [--no-sandbox] [--agent-cmd CMD]
                   [--mode m0|m1] [--control pointer|crib|starved] [--cases-v3 FILE] [--roots DIR]
                   [--family B|C] [--cases-real FILE] [--real-root DIR] [--views DIR]

Modes (v3; cases_v3.json lists the cases, tree.py builds the roots under WORK/roots):
  m0  handed (the default, as before): the catalog's context and question, the pool's logs at the
      catalog's logs_path.
  m1  cold start: the prompt gives the hutch (MFX), a vague time and the current date, no path and no
      window; WORK/roots/m1/<case> is mounted read-only at /sdf (the real MFX paths); an
      'ask-operator "<question>"' command answers from the case's fixed table and every question is
      appended to <run dir>/operator.jsonl.
Family C (real MFX logs; --mode m1 with --family C, or --case real-*): the cases of cases_real.json.  Each case
      gets a VIEW of the prepared root (--real-root, from 'real_mfx.py fetch') that holds only what existed at the
      case's 'now' (its today at the table's now_time, US Pacific): launch files stamped before it, other files
      modified before it, as hard links under VIEWS/<case>/root (default WORK/roots/real), mounted read-only at /sdf
      exactly as family B.  The prompt is cases_v3.json's m1 context at that time plus cases_real.json's question
      (today, vague phrase); ask-operator answers from the case's operator table (rules in cases_real.json).
Controls (one per arm; the arm name is still --arm):
  pointer   m1 only: the prompt also gives the log directory and the exact window of the keyed launch (family C:
            the target launch's folder, /sdf/home/m/mfxopr/<YYYY>/<MM> before the 2026-09-17 cutover)
  crib      m0 only: the case's crib (the key's mechanism) is put before the prompt
  starved   m0 or m1: the keyed launch's root-cause files are absent (WORK/roots/m0-starved, m1-starved);
            fault cases only; not for family C
With --mode m1 or a control and no --case, the cases are those of cases_v3.json (--family C: cases_real.json).  --skills may be
given twice (e.g. the skills and the hutch map) to install both sets in one skills folder.

An "arm" is one configuration under test, e.g. the skills at some commit, or no skills.
For each case and repeat this makes RESULTS_DIR/<arm>/<run id>/ (the id is opaque) with
  ws/                  the agent's working directory; ws/.claude/skills/<s>/ holds a copy of
                       each skill in SKILLS_DIR (a 'git archive' of psana/psana/skills at the
                       commit under test), or nothing for --skills none
  prompt.txt           the catalog's context and the case's question
  transcript.jsonl     the agent's stream-json output;  final.md  its last message
  meta.json            case, arm, repeat, model, seconds, exit status, tokens

The default agent is Claude Code headless:
  claude -p --output-format stream-json --verbose --allowedTools Bash,Read,Grep,Glob,Skill
         --setting-sources project --strict-mcp-config
(only the skills in ws/ are visible: no user skills, no MCP servers).

Sandbox.  Each agent runs under bubblewrap (bwrap) and sees:
  /work                        its working directory (read-write)
  <catalog logs_path>          the case's log directory, read-only, at the production path
  system directories           read-only
  the CLI's own state          ~/.claude with its history, projects, sessions and user skills
                               hidden, so one run cannot read another or the answer keys
and nothing else of the host: no home directory, no ssh keys, no other /tmp.  If the claude
CLI lives outside ~/.local and the system directories, add its folder with --expose DIR.  The network
stays up, because the agent has to reach its model.  GH_TOKEN and GITHUB_TOKEN are empty,
so a GitHub write cannot succeed (grade.py still counts the attempt).  TZ is
America/Los_Angeles, as on the hutch machines.

Another agent.  --agent-cmd CMD runs any program in place of Claude Code, inside the same
sandbox: the prompt arrives on stdin, the working directory is /work, the logs are at the
catalog's logs_path, and whatever it prints is its report (final.md).  Put the skills where
that agent looks with --skills-path, show its install with --expose DIR and its login with
--bind DIR.  For such a run grade.py cannot see the agent's commands, so read-only and
skills-loaded are 'not checked'; cause, launch, known issue and structure work as usual.

--no-sandbox runs the agent directly in ws/ with the real path of the logs in the prompt;
it is for tests with a scripted agent (--agent-cmd).  Each real run uses the model
subscription's usage; --dry-run writes the workspaces and prompts without starting an agent.
Standard library only, Python 3.6+.
"""

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

import real_mfx
from harvest import pool_id

AGENT = ['claude', '-p', '--output-format', 'stream-json', '--verbose', '--allowedTools', 'Bash,Read,Grep,Glob,Skill',
         '--setting-sources', 'project', '--strict-mcp-config']
HIDE = ['projects', 'skills', 'plugins', 'todos', 'shell-snapshots', 'file-history', 'sessions', 'backups', 'paste-cache',
        'feedback', 'cache', 'session-env']


def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_text(path, errors=None):
    with open(path, errors=errors) as f:
        return f.read()


def run_id(case, rep, salt=''):
    """Opaque folder name of one run; salt (mode and control) only when not the plain m0 run."""
    return 'r' + hashlib.sha1(('%s|%d' % (case, rep) + ('|' + salt if salt else '')).encode()).hexdigest()[:8]


ASK_OPERATOR = r'''#!/usr/bin/env python3
"""ask-operator "<question>": put one question to the operator who asked; prints the answer."""
import os, socket, sys
q = " ".join(sys.argv[1:]).strip()
if not q:
    print('usage: ask-operator "<question>"')
    sys.exit(2)
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(os.environ.get("ASK_OPERATOR_SOCK", "/run/operator/s/sock"))
s.sendall(q.encode("utf-8", "replace")[:4000] + b"\n")
s.shutdown(socket.SHUT_WR)
print(s.makefile(encoding="utf-8", errors="replace").read().strip())
'''


def operator_answer(table, case, question):
    """(answer, rule id) for one question: the first rule whose pattern matches and that the case answers."""
    q = question.lower()
    answers = case['m1'].get('answers') or {}
    for rule in table.get('operator_rules') or []:
        if rule['id'] in answers and any(re.search(p, q) for p in rule['match']):
            return answers[rule['id']], rule['id']
    return table.get('operator_default', "I don't know more than what I told you."), None


class Operator(object):
    """The ask-operator service of one run: a Unix socket outside the sandbox (the table never enters it)."""

    def __init__(self, table, case, log_path):
        self.table, self.case, self.log_path, self.lock = table, case, log_path, threading.Lock()
        self.dir = tempfile.mkdtemp(prefix='askop-', dir='/tmp' if os.path.isdir('/tmp') else None)   # short: a socket path has 108 bytes
        os.makedirs(os.path.join(self.dir, 'bin'))
        os.makedirs(os.path.join(self.dir, 's'))
        self.bin = os.path.join(self.dir, 'bin')
        self.sock = os.path.join(self.dir, 's', 'sock')
        path = os.path.join(self.bin, 'ask-operator')
        with open(path, 'w') as f:
            f.write(ASK_OPERATOR)
        os.chmod(path, 0o755)
        open(log_path, 'a').close()
        op = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                q = self.rfile.read(4096).decode('utf-8', 'replace').strip()
                answer, rule = operator_answer(op.table, op.case, q)
                with op.lock, open(op.log_path, 'a') as f:
                    f.write(json.dumps({'t': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                        'question': q, 'rule': rule, 'answer': answer}) + '\n')
                self.wfile.write(answer.encode('utf-8') + b'\n')

        self.server = socketserver.ThreadingUnixStreamServer(self.sock, Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def bwrap(self):
        return ['--ro-bind', self.bin, '/run/operator/bin', '--bind', os.path.dirname(self.sock), '/run/operator/s']

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)


def sandbox(ws, logs, logs_path, expose=(), bind=(), extra=()):
    """bwrap arguments: a root made of read-only system directories, /work, and the logs."""
    home = os.path.expanduser('~')
    a = ['bwrap', '--tmpfs', '/']
    for d in ('/usr', '/etc', '/opt', '/var', '/lib', '/lib64', '/bin', '/sbin'):
        if os.path.islink(d):
            a += ['--symlink', os.readlink(d), d]
        elif os.path.isdir(d):
            a += ['--ro-bind', d, d]
    a += ['--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp', '--tmpfs', '/run']
    if os.path.exists('/run/systemd/resolve'):
        a += ['--ro-bind', '/run/systemd/resolve', '/run/systemd/resolve']
    a += ['--dir', home]
    if os.path.isdir(os.path.join(home, '.claude')):
        a += ['--bind', os.path.join(home, '.claude'), os.path.join(home, '.claude')]
    if os.path.isdir(os.path.join(home, '.local')):
        a += ['--ro-bind', os.path.join(home, '.local'), os.path.join(home, '.local')]
    for name in HIDE:
        if os.path.isdir(os.path.join(home, '.claude', name)):
            a += ['--tmpfs', os.path.join(home, '.claude', name)]
    if os.path.isfile(os.path.join(home, '.claude', 'history.jsonl')):
        a += ['--ro-bind', '/dev/null', os.path.join(home, '.claude', 'history.jsonl')]
    seed = os.path.join(home, '.claude.json') if os.path.isfile(os.path.join(home, '.claude.json')) else '/dev/null'
    a += ['--ro-bind', seed, '/run/claude.json.src']
    for d in bind:                                   # another agent's own state, e.g. its login
        a += ['--bind', os.path.abspath(d), os.path.abspath(d)]
    for d in expose:                                 # e.g. where the claude CLI or its node runtime is installed
        a += ['--ro-bind', os.path.abspath(d), os.path.abspath(d)]
    if os.path.dirname(logs_path) != '/':
        a += ['--dir', os.path.dirname(logs_path)]
    a += ['--ro-bind', logs, logs_path] + list(extra)    # extra: the ask-operator command and its socket
    a += ['--bind', ws, '/work', '--chdir', '/work', '--setenv', 'HOME', home, '--unshare-pid', '--die-with-parent']
    # The CLI rewrites ~/.claude.json; give it a private copy
    return a + ['/bin/sh', '-c', 'cp /run/claude.json.src "$HOME/.claude.json"; exec "$@"', 'sh']


def read_stream(path):
    """(final text, result event, kind) of an agent's output.  kind is 'stream-json' for
    Claude Code's event stream, else 'text': the whole output is then the report."""
    result, last, ev_result, events = None, '', {}, 0
    raw = read_text(path, 'replace')
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or 'type' not in ev:
            continue
        events += 1
        if ev.get('type') == 'result':
            ev_result = ev
            if isinstance(ev.get('result'), str):
                result = ev['result']
        elif ev.get('type') == 'assistant':
            texts = [b.get('text', '') for b in (ev.get('message') or {}).get('content') or []
                     if isinstance(b, dict) and b.get('type') == 'text']
            if any(texts):
                last = '\n'.join(texts)
    if not events:
        return raw, {}, 'text'
    return (result if result is not None else last), ev_result, 'stream-json'


def now_text(now):
    return datetime.datetime.strptime(now, '%Y-%m-%d %H:%M').strftime('%A %Y-%m-%d, %H:%M')


def real_case_row(a, case):
    """A family-C case as run_one needs it: the operator table as 'answers' and the m1 fields of family B."""
    now = real_mfx.case_now(a.real, case)
    l = real_mfx.target_launch(case)
    return {'id': case['id'], 'family': 'C', 'm1': {
        'now': now, 'answers': case['operator'], 'keyed_stamp': real_mfx.stamp_of(case['target']),
        'keyed_dir': real_mfx.launch_dir(case['target']), 'keyed_files': [f['name'] for f in l['files']],
        'pointer': real_mfx.pointer(case),
        'question': a.real['question'].format(today_long=real_mfx.today_long(case['today']), phrase=case['phrase'])}}


def setup(cat, case, a):
    """(logs dir on the host, where the agent sees it, prompt, case-table row or None) for this mode and control."""
    if case.get('family') == 'C':
        v3 = case['row']
        logs, _rec = real_mfx.build_view(a.real_root, case['spec'], v3['m1']['now'], a.views)
        logs, mount = os.path.abspath(logs), '/sdf'
        prompt = a.table['m1_context'].format(now_text=now_text(v3['m1']['now'])) + '\n\n' + v3['m1']['question']
        if a.control == 'pointer':
            prompt += '\n\n' + v3['m1']['pointer']
        if a.preface:
            prompt = a.preface + '\n\n' + prompt
        if a.no_sandbox:
            prompt = prompt.replace(mount + '/', logs + '/')
        return logs, mount, prompt, v3
    v3 = a.table_cases.get(case['id']) if a.table_cases else None
    roots = a.roots or os.path.join(a.work, 'roots')
    if a.mode == 'm1':
        logs = os.path.abspath(os.path.join(roots, 'm1-starved' if a.control == 'starved' else 'm1', case['id']))
        mount = '/sdf'
        prompt = a.table['m1_context'].format(now_text=now_text(v3['m1']['now'])) + '\n\n' + v3['m1']['question']
        if a.control == 'pointer':
            prompt += '\n\n' + v3['m1']['pointer']
    else:
        logs = os.path.abspath(os.path.join(a.work, 'pools', pool_id(case['pool']), 'logs'))
        if a.control == 'starved':
            logs = os.path.abspath(os.path.join(roots, 'm0-starved', case['id'], 'logs'))
        mount = cat['logs_path']
        prompt = cat['context'] + '\n\n' + case['question']
        if a.control == 'crib':
            prompt = a.table['crib_preface'].format(crib=v3['crib']) + '\n\n' + prompt
    if not os.path.isdir(logs):
        raise SystemExit('%s: %s does not exist; build it with tree.py --work %s' % (case['id'], logs, a.work))
    if a.preface:
        prompt = a.preface + '\n\n' + prompt
    if a.no_sandbox:
        prompt = prompt.replace(mount + '/' if a.mode == 'm1' else mount, logs + '/' if a.mode == 'm1' else logs)
    return logs, mount, prompt, v3


def run_one(cat, case, a, rep):
    if case.get('family') != 'C':
        pool = read_json(os.path.join(a.work, 'pools', pool_id(case['pool']), 'pool.json'))
        if pool.get('leaks') and not a.allow_leaks:
            raise SystemExit('%s: harvest found leaks in its pool; fix them before running' % case['id'])
    salt = '' if a.mode == 'm0' and not a.control else '%s|%s' % (a.mode, a.control or '')
    d = os.path.abspath(os.path.join(a.out, a.arm, run_id(case['id'], rep, salt)))
    meta_path = os.path.join(d, 'meta.json')
    if a.resume and os.path.exists(meta_path):
        old = read_json(meta_path)
        if old.get('exit') == 0 and not old.get('error') and os.path.getsize(os.path.join(d, 'final.md')) > 0:
            return old, True
    logs, mount, prompt, v3 = setup(cat, case, a)
    if os.path.exists(d):
        shutil.rmtree(d)
    ws = os.path.join(d, 'ws')
    os.makedirs(ws)
    for sk in a.skills_dirs:
        for s in sorted(os.listdir(sk)):
            if os.path.exists(os.path.join(sk, s, 'SKILL.md')):
                shutil.copytree(os.path.join(sk, s), os.path.join(ws, a.skills_path, s))
    with open(os.path.join(d, 'prompt.txt'), 'w') as f:
        f.write(prompt)
    cmd = shlex.split(a.agent_cmd) if a.agent_cmd else AGENT + (['--model', a.model] if a.model else [])
    meta = {'case': case['id'], 'arm': a.arm, 'repeat': rep,
            'skills': ','.join(os.path.abspath(s) for s in a.skills_dirs) or 'none',
            'model_flag': a.model, 'sandbox': not a.no_sandbox, 'preface': a.preface, 'mode': a.mode, 'control': a.control,
            'logs_src': logs, 'logs_mount': mount,
            'started': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    if v3 and a.mode == 'm1':
        meta.update(now=v3['m1']['now'], keyed_stamp=v3['m1'].get('keyed_stamp'), keyed_dir=v3['m1'].get('keyed_dir'))
    meta['family'] = 'C' if case.get('family') == 'C' else ('B' if a.mode == 'm1' else 'A')
    if a.dry_run:
        meta['dry_run'] = True
    else:
        env = dict(os.environ, GH_TOKEN='', GITHUB_TOKEN='', GH_CONFIG_DIR='/nonexistent', TZ='America/Los_Angeles')
        env.pop('DAQ_DIAG_REPORT_DIR', None)
        optable = a.real if case.get('family') == 'C' else a.table          # family C: its own rules and default answer
        op = Operator(optable, v3, os.path.join(d, 'operator.jsonl')) if a.mode == 'm1' else None
        extra = []
        if op and a.no_sandbox:
            env.update(PATH=op.bin + os.pathsep + env.get('PATH', ''), ASK_OPERATOR_SOCK=op.sock, DAQ_EVAL_SDF=logs)
        elif op:
            env['PATH'] = '/run/operator/bin' + os.pathsep + env.get('PATH', '')
            env.pop('ASK_OPERATOR_SOCK', None)
            extra = op.bwrap()
        full = cmd if a.no_sandbox else sandbox(ws, logs, mount, a.expose, a.bind, extra) + cmd
        t0 = time.time()
        try:
            with open(os.path.join(d, 'transcript.jsonl'), 'w') as tr, open(os.path.join(d, 'stderr.txt'), 'w') as er:
                try:
                    p = subprocess.run(full, input=prompt, stdout=tr, stderr=er, cwd=ws, env=env,
                                       universal_newlines=True, timeout=a.timeout)
                    meta['exit'] = p.returncode
                except subprocess.TimeoutExpired:
                    meta['exit'] = 'timeout'
        finally:
            if op:
                op.close()
        meta['seconds'] = round(time.time() - t0, 1)
        final, res, meta['transcript'] = read_stream(os.path.join(d, 'transcript.jsonl'))
        with open(os.path.join(d, 'final.md'), 'w') as f:
            f.write(final)
        usage = res.get('usage') or {}
        meta.update(turns=res.get('num_turns'), cost_usd=res.get('total_cost_usd'), total_cost_usd=res.get('total_cost_usd'),
                    output_tokens=usage.get('output_tokens'), model=next(iter(res.get('modelUsage') or {}), None))
        if op:
            with open(os.path.join(d, 'operator.jsonl')) as f:
                meta['operator_questions'] = sum(1 for _ in f)
        if res.get('is_error') or not final.strip():
            meta['error'] = (final or read_text(os.path.join(d, 'stderr.txt')))[:300]
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=1)
    return meta, False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--catalog', default=os.path.join(here, 'catalog.json'))
    ap.add_argument('--work', required=True, help='harvest.py --out folder')
    ap.add_argument('--arm', required=True, help='a name for this configuration, e.g. skills-181 or none')
    ap.add_argument('--skills', required=True, action='append',
                    help="folder of <skill>/SKILL.md, or 'none'; give it twice to install two sets in one skills folder")
    ap.add_argument('--mode', choices=['m0', 'm1'], default='m0', help='m0 handed (default), m1 cold start')
    ap.add_argument('--control', choices=['pointer', 'crib', 'starved'], help='a control arm (see above)')
    ap.add_argument('--cases-v3', default=os.path.join(here, 'cases_v3.json'), help='the v3 case table (default %(default)s)')
    ap.add_argument('--roots', help='where tree.py built the roots (default WORK/roots)')
    ap.add_argument('--family', choices=['B', 'C'], help='m1 only: run every case of this family (default B; --case real-* means C)')
    ap.add_argument('--cases-real', default=os.path.join(here, 'cases_real.json'), help='the family-C case table (default %(default)s)')
    ap.add_argument('--real-root', help="family C: the prepared root of real MFX logs ('real_mfx.py fetch --dest')")
    ap.add_argument('--views', help='family C: where the per-case root views go (default WORK/roots/real)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--set', choices=['core', 'full'], default='core', help="'full' adds the extra cases")
    ap.add_argument('--case', action='append')
    ap.add_argument('--repeats', type=int, default=1)
    ap.add_argument('--first-repeat', type=int, default=1)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--model')
    ap.add_argument('--preface', help='text put before every prompt of this arm, e.g. an instruction to load a skill '
                                      'first; it makes the arm a different experiment, so give it its own --arm name')
    ap.add_argument('--agent-cmd')
    ap.add_argument('--timeout', type=int, default=1800, help='seconds per run (default %(default)d)')
    ap.add_argument('--resume', action='store_true', help='keep runs that already finished without error')
    ap.add_argument('--no-sandbox', action='store_true')
    ap.add_argument('--skills-path', default=os.path.join('.claude', 'skills'),
                    help='where in the working directory the skills are copied (default %(default)s)')
    ap.add_argument('--bind', action='append', default=[], metavar='DIR',
                    help='also show this directory in the sandbox, read-write (repeatable): another agent\'s login or state')
    ap.add_argument('--expose', action='append', default=[], metavar='DIR',
                    help='also show this directory in the sandbox, read-only (repeatable); needed when the claude CLI '
                         'is installed outside ~/.local and the system directories')
    ap.add_argument('--allow-leaks', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    cat = read_json(a.catalog)
    a.skills_dirs = [s for s in a.skills if s != 'none']
    if 'none' in a.skills and a.skills_dirs:
        ap.error("--skills none cannot be combined with a skills folder")
    if a.control == 'pointer' and a.mode != 'm1' or a.control == 'crib' and a.mode != 'm0':
        ap.error('--control pointer needs --mode m1; --control crib needs --mode m0')
    a.table, a.table_cases, a.real = None, None, None
    real_ids = []
    if (a.family or any(c.startswith('real-') for c in a.case or [])) and a.mode != 'm1':
        ap.error('--family and the family-C cases (real-*) need --mode m1')
    if a.mode == 'm1' and (a.family == 'C' or any(c.startswith('real-') for c in a.case or [])):
        with open(a.cases_real) as f:
            a.real = json.load(f)
        real_cases = dict((c['id'], c) for c in a.real['cases'])
        real_ids = [c for c in a.case or [] if c in real_cases] if a.case else ([c['id'] for c in a.real['cases']] if a.family == 'C' else [])
        if a.family == 'C' and a.case and len(real_ids) != len(a.case):
            ap.error('not in %s: %s' % (a.cases_real, ', '.join(c for c in a.case if c not in real_cases)))
        if a.control in ('starved', 'crib'):
            ap.error('--control %s has no family-C cases' % a.control)
        if not a.real_root:
            ap.error('family C needs --real-root (the prepared root of real MFX logs)')
        a.real_root = os.path.abspath(a.real_root)
        a.views = os.path.abspath(a.views or os.path.join(a.work, 'roots', 'real'))
    if a.mode == 'm1' or a.control:
        a.table = read_json(a.cases_v3)
        a.table_cases = dict((c['id'], c) for c in a.table['cases'])
        unknown = [c for c in a.case or [] if c not in a.table_cases and c not in real_ids]
        if unknown:
            ap.error('not in %s: %s' % (a.cases_v3, ', '.join(unknown)))
        ids = [c for c in (a.case or ([] if a.family == 'C' else [c['id'] for c in a.table['cases']]))
               if c not in real_ids and (a.control != 'starved' or a.table_cases[c].get('starve_files'))]
        todo = [(c, r) for c in cat['cases'] if c['id'] in ids for r in range(a.first_repeat, a.first_repeat + a.repeats)]
        for cid in real_ids:
            spec = real_cases[cid]
            c = {'id': cid, 'family': 'C', 'spec': spec}
            c['row'] = real_case_row(a, spec)
            real_mfx.build_view(a.real_root, spec, c['row']['m1']['now'], a.views)     # before any job: one build per case
            todo += [(c, r) for r in range(a.first_repeat, a.first_repeat + a.repeats)]
    else:
        todo = [(c, r) for c in cat['cases'] if (a.case and c['id'] in a.case) or (not a.case and c['set'] in (('core', 'full') if a.set == 'full' else ('core',)))
                for r in range(a.first_repeat, a.first_repeat + a.repeats)]
    bad = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = {ex.submit(run_one, cat, c, a, r): (c, r) for c, r in todo}
        for f in concurrent.futures.as_completed(futs):
            c, r = futs[f]
            meta, kept = f.result()
            bad += bool(meta.get('error')) or meta.get('exit', 0) != 0
            print('%-10s %-26s r%d exit=%s %6ss %s%s' % (a.arm, c['id'], r, meta.get('exit', 'dry'), meta.get('seconds', '-'),
                                                       '(kept) ' if kept else '', (meta.get('error') or '')[:80].replace('\n', ' ')))
            sys.stdout.flush()
    print('%d runs, %d with errors' % (len(todo), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
