"""Run an agent on harvested eval cases and keep what grade.py needs.

    python3 run.py --cases CASES_DIR --skills SKILLS_DIR --out RESULTS_DIR
                   [--case ID ...] [--repeats N] [--agent-cmd CMD] [--dry-run]

For each case and repeat, makes RESULTS_DIR/<case_dir>__r<N>/ a fresh workspace, named
opaquely so the path does not hint at the case (meta.json, written after the run,
records the case id):
  logs/                 a copy of the case's logs (the agent may do anything to the copy)
  .claude/skills/<s>/   a copy of each skill in SKILLS_DIR (e.g. a 'git archive' of
                        psana/psana/skills at the commit under test)
  prompt.txt            the prompt, from the catalog's templates and case.json
then runs the agent there with that prompt on stdin and saves
  transcript.jsonl      its stream-json output, final.md its last message, meta.json.

The default agent is Claude Code headless:
  claude -p --output-format stream-json --verbose --allowedTools Bash,Read,Grep,Glob,Skill
GitHub writes cannot succeed: GH_TOKEN, GITHUB_TOKEN and GH_CONFIG_DIR are pointed at
nothing, so a 'gh issue create' fails (grade.py still counts the attempt).  Nothing here
can reach a DAQ: the cases are logs only.

Each run uses the subscription's usage limit; --dry-run writes the workspaces and prompts
without starting an agent.  Standard library only, Python 3.6+.
"""

import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from harvest import case_dir

DEFAULT_AGENT = ('claude -p --output-format stream-json --verbose '
                 '--allowedTools Bash,Read,Grep,Glob,Skill')


def prompt_for(catalog, case, info, logs):
    t = catalog['prompts']
    first = info.get('first') or ''
    last = info.get('last') or first
    fill = {'logs': logs, 'date': first[:10], 'start': first[11:16], 'end': last[11:16]}
    return (t['context'] + '\n\n' + t[case['prompt']]).format(**fill)


def final_from_stream(path):
    """The 'result' text of a stream-json transcript, else the last assistant text."""
    result, last = None, ''
    for line in open(path, errors='replace'):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get('type') == 'result' and isinstance(ev.get('result'), str):
            result = ev['result']
        elif ev.get('type') == 'assistant':
            texts = [b.get('text', '') for b in (ev.get('message') or {}).get('content') or []
                     if isinstance(b, dict) and b.get('type') == 'text']
            if any(texts):
                last = '\n'.join(texts)
    return result if result is not None else last


def run_one(catalog, case, cases_dir, skills, out, rep, agent_cmd, dry, timeout):
    src = os.path.join(cases_dir, case_dir(case['id']))
    info = json.load(open(os.path.join(src, 'case.json')))
    if info.get('leaks'):
        raise SystemExit('%s: harvest found leaks; fix the case before running it' % case['id'])
    ws = os.path.abspath(os.path.join(out, '%s__r%d' % (case_dir(case['id']), rep)))
    if os.path.exists(ws):
        shutil.rmtree(ws)
    shutil.copytree(os.path.join(src, 'logs'), os.path.join(ws, 'logs'))
    for s in sorted(os.listdir(skills)):
        if os.path.exists(os.path.join(skills, s, 'SKILL.md')):
            shutil.copytree(os.path.join(skills, s), os.path.join(ws, '.claude', 'skills', s))
    prompt = prompt_for(catalog, case, info, os.path.join(ws, 'logs'))
    open(os.path.join(ws, 'prompt.txt'), 'w').write(prompt)
    meta = {'case': case['id'], 'repeat': rep, 'skills': os.path.abspath(skills), 'agent_cmd': agent_cmd,
            'started': datetime.datetime.utcnow().isoformat() + 'Z'}
    if dry:
        meta['dry_run'] = True
    else:
        env = dict(os.environ, GH_TOKEN='', GITHUB_TOKEN='', GH_CONFIG_DIR=tempfile.mkdtemp(prefix='nogh-'))
        t0 = time.time()
        with open(os.path.join(ws, 'transcript.jsonl'), 'w') as tr, \
                open(os.path.join(ws, 'stderr.txt'), 'w') as er:
            try:
                p = subprocess.run(shlex.split(agent_cmd), input=prompt, stdout=tr, stderr=er, cwd=ws,
                                   env=env, universal_newlines=True, timeout=timeout)
                meta['exit'] = p.returncode
            except subprocess.TimeoutExpired:
                meta['exit'] = 'timeout'
        meta['seconds'] = round(time.time() - t0, 1)
        open(os.path.join(ws, 'final.md'), 'w').write(final_from_stream(os.path.join(ws, 'transcript.jsonl')))
    json.dump(meta, open(os.path.join(ws, 'meta.json'), 'w'), indent=1)
    return ws, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--catalog', default=os.path.join(here, 'catalog.json'))
    ap.add_argument('--cases', required=True, help='harvest.py --out folder')
    ap.add_argument('--skills', required=True, help='folder of <skill>/SKILL.md')
    ap.add_argument('--out', required=True)
    ap.add_argument('--case', action='append')
    ap.add_argument('--repeats', type=int, default=1)
    ap.add_argument('--agent-cmd', default=DEFAULT_AGENT)
    ap.add_argument('--timeout', type=int, default=1800, help='seconds per run (default %(default)d)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    catalog = json.load(open(a.catalog))
    os.makedirs(a.out, exist_ok=True)
    for case in catalog['cases']:
        if a.case and case['id'] not in a.case:
            continue
        for rep in range(1, a.repeats + 1):
            ws, meta = run_one(catalog, case, a.cases, a.skills, a.out, rep, a.agent_cmd, a.dry_run, a.timeout)
            print('%-28s r%d exit=%s %ss' % (case['id'], rep, meta.get('exit', 'dry'), meta.get('seconds', '-')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
