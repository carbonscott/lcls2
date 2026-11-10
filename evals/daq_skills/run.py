"""Run an agent on eval cases and keep what grade.py needs.

    python3 run.py --work WORK_DIR --arm NAME --skills SKILLS_DIR|none --out RESULTS_DIR
                   [--set core|full] [--case ID ...] [--repeats N] [--jobs N] [--model M]
                   [--resume] [--dry-run] [--no-sandbox] [--agent-cmd CMD]

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
import shlex
import shutil
import subprocess
import sys
import time

from harvest import pool_id

AGENT = ['claude', '-p', '--output-format', 'stream-json', '--verbose', '--allowedTools', 'Bash,Read,Grep,Glob,Skill',
         '--setting-sources', 'project', '--strict-mcp-config']
HIDE = ['projects', 'skills', 'plugins', 'todos', 'shell-snapshots', 'file-history', 'sessions', 'backups', 'paste-cache',
        'feedback', 'cache', 'session-env']


def run_id(case, rep):
    return 'r' + hashlib.sha1(('%s|%d' % (case, rep)).encode()).hexdigest()[:8]


def sandbox(ws, logs, logs_path, expose=()):
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
    a += ['--dir', home, '--bind', os.path.join(home, '.claude'), os.path.join(home, '.claude')]
    if os.path.isdir(os.path.join(home, '.local')):
        a += ['--ro-bind', os.path.join(home, '.local'), os.path.join(home, '.local')]
    for name in HIDE:
        if os.path.isdir(os.path.join(home, '.claude', name)):
            a += ['--tmpfs', os.path.join(home, '.claude', name)]
    if os.path.isfile(os.path.join(home, '.claude', 'history.jsonl')):
        a += ['--ro-bind', '/dev/null', os.path.join(home, '.claude', 'history.jsonl')]
    a += ['--ro-bind', os.path.join(home, '.claude.json'), '/run/claude.json.src']
    for d in expose:                                 # e.g. where the claude CLI or its node runtime is installed
        a += ['--ro-bind', os.path.abspath(d), os.path.abspath(d)]
    a += ['--dir', os.path.dirname(logs_path), '--ro-bind', logs, logs_path, '--bind', ws, '/work', '--chdir', '/work',
          '--setenv', 'HOME', home, '--unshare-pid', '--die-with-parent']
    # The CLI rewrites ~/.claude.json; give it a private copy
    return a + ['/bin/sh', '-c', 'cp /run/claude.json.src "$HOME/.claude.json"; exec "$@"', 'sh']


def read_stream(path):
    """(final text, result event) of a stream-json transcript."""
    result, last, ev_result = None, '', {}
    for line in open(path, errors='replace'):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get('type') == 'result':
            ev_result = ev
            if isinstance(ev.get('result'), str):
                result = ev['result']
        elif ev.get('type') == 'assistant':
            texts = [b.get('text', '') for b in (ev.get('message') or {}).get('content') or []
                     if isinstance(b, dict) and b.get('type') == 'text']
            if any(texts):
                last = '\n'.join(texts)
    return (result if result is not None else last), ev_result


def run_one(cat, case, a, rep):
    logs = os.path.abspath(os.path.join(a.work, 'pools', pool_id(case['pool']), 'logs'))
    pool = json.load(open(os.path.join(os.path.dirname(logs), 'pool.json')))
    if pool.get('leaks') and not a.allow_leaks:
        raise SystemExit('%s: harvest found leaks in its pool; fix them before running' % case['id'])
    d = os.path.abspath(os.path.join(a.out, a.arm, run_id(case['id'], rep)))
    meta_path = os.path.join(d, 'meta.json')
    if a.resume and os.path.exists(meta_path):
        old = json.load(open(meta_path))
        if old.get('exit') == 0 and not old.get('error') and os.path.getsize(os.path.join(d, 'final.md')) > 0:
            return old, True
    if os.path.exists(d):
        shutil.rmtree(d)
    ws = os.path.join(d, 'ws')
    os.makedirs(ws)
    if a.skills != 'none':
        for s in sorted(os.listdir(a.skills)):
            if os.path.exists(os.path.join(a.skills, s, 'SKILL.md')):
                shutil.copytree(os.path.join(a.skills, s), os.path.join(ws, '.claude', 'skills', s))
    prompt = cat['context'] + '\n\n' + case['question']
    if a.no_sandbox:
        prompt = prompt.replace(cat['logs_path'], logs)
    open(os.path.join(d, 'prompt.txt'), 'w').write(prompt)
    cmd = shlex.split(a.agent_cmd) if a.agent_cmd else AGENT + (['--model', a.model] if a.model else [])
    meta = {'case': case['id'], 'arm': a.arm, 'repeat': rep, 'skills': 'none' if a.skills == 'none' else os.path.abspath(a.skills),
            'model_flag': a.model, 'sandbox': not a.no_sandbox,
            'started': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    if a.dry_run:
        meta['dry_run'] = True
    else:
        env = dict(os.environ, GH_TOKEN='', GITHUB_TOKEN='', GH_CONFIG_DIR='/nonexistent', TZ='America/Los_Angeles')
        env.pop('DAQ_DIAG_REPORT_DIR', None)
        full = cmd if a.no_sandbox else sandbox(ws, logs, cat['logs_path'], a.expose) + cmd
        t0 = time.time()
        with open(os.path.join(d, 'transcript.jsonl'), 'w') as tr, open(os.path.join(d, 'stderr.txt'), 'w') as er:
            try:
                p = subprocess.run(full, input=prompt, stdout=tr, stderr=er, cwd=ws, env=env,
                                   universal_newlines=True, timeout=a.timeout)
                meta['exit'] = p.returncode
            except subprocess.TimeoutExpired:
                meta['exit'] = 'timeout'
        meta['seconds'] = round(time.time() - t0, 1)
        final, res = read_stream(os.path.join(d, 'transcript.jsonl'))
        open(os.path.join(d, 'final.md'), 'w').write(final)
        usage = res.get('usage') or {}
        meta.update(turns=res.get('num_turns'), cost_usd=res.get('total_cost_usd'), output_tokens=usage.get('output_tokens'),
                    model=next(iter(res.get('modelUsage') or {}), None))
        if res.get('is_error') or not final.strip():
            meta['error'] = (final or open(os.path.join(d, 'stderr.txt')).read())[:300]
    json.dump(meta, open(meta_path, 'w'), indent=1)
    return meta, False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--catalog', default=os.path.join(here, 'catalog.json'))
    ap.add_argument('--work', required=True, help='harvest.py --out folder')
    ap.add_argument('--arm', required=True, help='a name for this configuration, e.g. skills-181 or none')
    ap.add_argument('--skills', required=True, help="folder of <skill>/SKILL.md, or 'none'")
    ap.add_argument('--out', required=True)
    ap.add_argument('--set', choices=['core', 'full'], default='core', help="'full' adds the extra cases")
    ap.add_argument('--case', action='append')
    ap.add_argument('--repeats', type=int, default=1)
    ap.add_argument('--first-repeat', type=int, default=1)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--model')
    ap.add_argument('--agent-cmd')
    ap.add_argument('--timeout', type=int, default=1800, help='seconds per run (default %(default)d)')
    ap.add_argument('--resume', action='store_true', help='keep runs that already finished without error')
    ap.add_argument('--no-sandbox', action='store_true')
    ap.add_argument('--expose', action='append', default=[], metavar='DIR',
                    help='also show this directory in the sandbox, read-only (repeatable); needed when the claude CLI '
                         'is installed outside ~/.local and the system directories')
    ap.add_argument('--allow-leaks', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    cat = json.load(open(a.catalog))
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
