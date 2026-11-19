"""Run a batch of v3 eval cells, score them, and write the rows verdict.py reads.

    python3 pilot.py --out OUT --work WORK [--real-root ROOT] [--skills SK] [--map MAP]
                     --cell FAMILY/ARM[/MODEL[/CASES[/REPEATS]]] ... | --cells FILE
                     --budget-left USD [--jobs 2] [--resume] [--dry-run]
                     [--agent-usd X] [--scorer-usd Y] [--no-score]
    python3 verdict.py OUT/rows.json

A cell is one (family, arm, model) over some cases and repeats:
  family  A (mode m0, the catalog pools), B (mode m1, tree.py's MFX-shaped tree), C (mode m1, real MFX logs)
  arm     none | skills | map | both | pointer | crib | starved      (pointer: B, C; crib: A; starved: A, B)
          skills installs --skills, map installs --map (the folder holding hutch-resources/), both installs both
  model   default (no --model flag) | haiku | any model name run.py accepts      (default: --model)
  cases   all | id+id+...  ('all': the family's cases, fault cases only for starved)   (default: --cases)
  repeats N: repeats 1..N                                                            (default: --repeats)
e.g. --cell C/none/haiku/all/1 --cell C/skills/haiku/real-qadc-run.  --cells FILE takes a JSON list of
{"family", "arm", "model", "cases": [...] or "all", "repeats"} objects.

Each run is one 'run.py --case C --first-repeat R --repeats 1' process; at most --jobs of them run at once
(default 2), each one agent.  Results go to OUT/<family>.<arm>.<model>/<run id>/ (run.py's layout).  With
--resume, runs that already finished are kept.  Then 'score.py --results OUT' and 'evidence.py --results OUT'
(scorer calls also at most --jobs at once), and OUT/rows.json: one row per run of the batch in verdict.py's
schema (run_id, family, case, arm, mode, model, repeat, healthy, cause_pass, healthy_outcome, located, calls, calls_no_guidance,
cost_usd, seconds; plus exit and error).  OUT/usage.json has the batch's usage: agent and scorer separately.

Budget.  Before anything starts, pilot.py prints a per-run estimate (agent and scorer) and the projection for
the runs still to do; it refuses (exit 2) if the projection exceeds --budget-left.  The agent estimate is the
larger of the model's table value (AGENT_USD) and 1.2 x the mean usage of that model's finished runs in OUT;
--agent-usd and --scorer-usd replace them.

--agent-cmd, --no-sandbox, --extract-cmd and --judge-cmd are passed through (tests with scripted agents).
Standard library only, Python 3.6+.
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time

import real_mfx
from run import run_id

HERE = os.path.dirname(os.path.abspath(__file__))
FAMILY_MODE = {'A': 'm0', 'B': 'm1', 'C': 'm1'}
ARMS = {'none': None, 'skills': None, 'map': None, 'both': None, 'pointer': 'pointer', 'crib': 'crib', 'starved': 'starved'}
ALLOWED = {'A': ('none', 'skills', 'map', 'both', 'crib', 'starved'), 'B': ('none', 'skills', 'map', 'both', 'pointer', 'starved'),
           'C': ('none', 'skills', 'map', 'both', 'pointer')}
AGENT_USD = {'default': 2.00, 'haiku': 0.10}          # per run; P8 expects $1.0-2.5 for a default-model M1 run
OTHER_MODEL_USD = 2.00
SCORER_USD = 0.06                                      # one extraction + 3 judge votes (sonnet): $0.038 a report on v2; + one conclusion call (m1)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def parse_cell(text, a):
    """'B/none/haiku/all/2' -> cell dict, missing parts from the defaults."""
    parts = text.split('/')
    if not 2 <= len(parts) <= 5:
        raise SystemExit('--cell %r: want FAMILY/ARM[/MODEL[/CASES[/REPEATS]]]' % text)
    cell = {'family': parts[0], 'arm': parts[1], 'model': parts[2] if len(parts) > 2 and parts[2] else a.model,
            'cases': parts[3] if len(parts) > 3 and parts[3] else a.cases,
            'repeats': int(parts[4]) if len(parts) > 4 and parts[4] else a.repeats}
    return cell


def normalize(cell, tables):
    fam, arm = cell['family'], cell['arm']
    if fam not in FAMILY_MODE:
        raise SystemExit('cell %s: family must be A, B or C' % cell)
    if arm not in ALLOWED[fam]:
        raise SystemExit('cell %s: arm %s is not run on family %s (allowed: %s)' % (cell, arm, fam, ', '.join(ALLOWED[fam])))
    cases = cell.get('cases', 'all')
    if cases == 'all':
        if fam == 'C':
            cases = [c['id'] for c in tables['real']['cases']]
        else:
            cases = [c['id'] for c in tables['v3']['cases'] if arm != 'starved' or c.get('starve_files')]
    elif isinstance(cases, str):
        cases = [c for c in cases.replace(',', '+').split('+') if c]
    known = set(c['id'] for c in tables['real']['cases']) if fam == 'C' else set(c['id'] for c in tables['v3']['cases'])
    bad = [c for c in cases if c not in known]
    if bad:
        raise SystemExit('cell %s/%s: unknown cases for family %s: %s' % (fam, arm, fam, ', '.join(bad)))
    if arm == 'starved':
        starvable = set(c['id'] for c in tables['v3']['cases'] if c.get('starve_files'))
        cases = [c for c in cases if c in starvable]
    model = cell.get('model') or 'default'
    return {'family': fam, 'arm': arm, 'model': model, 'cases': cases, 'repeats': int(cell.get('repeats', 1)),
            'mode': FAMILY_MODE[fam], 'control': ARMS[arm], 'folder': '%s.%s.%s' % (fam, arm, model)}


def plan(cells):
    """[(cell, case, repeat, run dir relative to OUT)] in a fixed order."""
    out, seen = [], set()
    for cell in cells:
        for case in cell['cases']:
            for rep in range(1, cell['repeats'] + 1):
                salt = '' if cell['mode'] == 'm0' and not cell['control'] else '%s|%s' % (cell['mode'], cell['control'] or '')
                rel = os.path.join(cell['folder'], run_id(case, rep, salt))
                if rel not in seen:
                    seen.add(rel)
                    out.append((cell, case, rep, rel))
    return out


def finished(run_dir):
    """run.py --resume's rule: exit 0, no error, a non-empty final.md."""
    try:
        m = read_json(os.path.join(run_dir, 'meta.json'))
        return m.get('exit') == 0 and not m.get('error') and not m.get('dry_run') and os.path.getsize(os.path.join(run_dir, 'final.md')) > 0
    except (OSError, ValueError):
        return False


def observed_usd(out, model):
    """Mean agent usage of the finished runs of this model in OUT (None if fewer than 3)."""
    v = []
    for arm in os.listdir(out) if os.path.isdir(out) else []:
        if not arm.endswith('.' + model) or not os.path.isdir(os.path.join(out, arm)):
            continue
        for rid in os.listdir(os.path.join(out, arm)):
            d = os.path.join(out, arm, rid)
            if finished(d):
                c = read_json(os.path.join(d, 'meta.json')).get('cost_usd')
                if c is not None:
                    v.append(c)
    return sum(v) / len(v) if len(v) >= 3 else None


def estimate(a, todo_models):
    """{model: (agent usd per run, where it comes from)}, scorer usd per run."""
    est = {}
    for model in sorted(set(todo_models)):
        if a.agent_usd is not None:
            est[model] = (a.agent_usd, '--agent-usd')
            continue
        base = AGENT_USD.get(model, OTHER_MODEL_USD)
        obs = observed_usd(a.out, model)
        if obs is not None and 1.2 * obs > base:
            est[model] = (round(1.2 * obs, 4), '1.2 x mean of %s runs in OUT' % model)
        else:
            est[model] = (base, 'table' + (' (OUT mean %.3f)' % obs if obs is not None else ''))
    return est, (a.scorer_usd if a.scorer_usd is not None else SCORER_USD)


def run_cmd(a, cell, case, rep):
    cmd = [sys.executable, os.path.join(HERE, 'run.py'), '--work', a.work, '--out', a.out, '--arm', cell['folder'],
           '--mode', cell['mode'], '--case', case, '--first-repeat', str(rep), '--repeats', '1', '--jobs', '1',
           '--catalog', a.catalog, '--cases-v3', a.cases_v3, '--timeout', str(a.timeout)]
    arm = cell['arm']
    skills = {'none': [], 'pointer': [], 'crib': [], 'starved': [], 'skills': [a.skills], 'map': [a.map], 'both': [a.skills, a.map]}[arm]
    for s in skills or ['none']:
        cmd += ['--skills', s]
    if cell['control']:
        cmd += ['--control', cell['control']]
    if cell['model'] != 'default':
        cmd += ['--model', cell['model']]
    if cell['family'] == 'C':
        cmd += ['--family', 'C', '--cases-real', a.cases_real, '--real-root', a.real_root, '--views', a.views]
    if a.roots:
        cmd += ['--roots', a.roots]
    if a.resume:
        cmd.append('--resume')
    if a.agent_cmd:
        cmd += ['--agent-cmd', a.agent_cmd]
    if a.no_sandbox:
        cmd.append('--no-sandbox')
    for e in a.expose:
        cmd += ['--expose', e]
    return cmd


def score_and_evidence(a):
    """Run score.py and evidence.py over OUT; (scored rows by id, evidence rows by id, scorer meta)."""
    scored_path = os.path.join(a.out, 'scored.json')
    cmd = [sys.executable, os.path.join(HERE, 'score.py'), '--results', a.out, '--out', scored_path,
           '--summary', os.path.join(a.out, 'scored.txt'), '--jobs', str(max(1, a.jobs)), '--keys', a.keys,
           '--cases-v3', a.cases_v3, '--cases-real', a.cases_real]
    if a.extract_cmd:
        cmd += ['--extract-cmd', a.extract_cmd]
    if a.judge_cmd:
        cmd += ['--judge-cmd', a.judge_cmd]
    with open(os.path.join(a.out, 'score.log'), 'w') as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    print('score.py exit %d (log: %s)' % (rc, os.path.join(a.out, 'score.log')))
    scored = read_json(scored_path) if os.path.exists(scored_path) else {'rows': [], 'meta': {}}
    ev = subprocess.run([sys.executable, os.path.join(HERE, 'evidence.py'), '--results', a.out, '--work', a.work, '--json',
                         '--write', '--catalog', a.catalog, '--cases-v3', a.cases_v3, '--cases-real', a.cases_real],
                        stdout=subprocess.PIPE, universal_newlines=True)
    print('evidence.py exit %d' % ev.returncode)
    evid = dict((r['run'], r) for r in json.loads(ev.stdout or '[]'))
    return dict((r['id'], r) for r in scored.get('rows', [])), evid, scored.get('meta', {})


def rows_for(a, todo, tables, scored, evid):
    healthy = dict((c['id'], bool(c.get('healthy'))) for c in tables['v3']['cases'])
    healthy.update((c['id'], c['kind'] == 'healthy') for c in tables['real']['cases'])
    rows = []
    for cell, case, rep, rel in todo:
        d = os.path.join(a.out, rel)
        meta = read_json(os.path.join(d, 'meta.json')) if os.path.exists(os.path.join(d, 'meta.json')) else {}
        rid = rel.replace(os.sep, '/')
        s, e = scored.get(rid) or {}, evid.get(rid) or {}
        o = s.get('outcome') or {}
        h = healthy[case]
        rows.append({'run_id': rid, 'family': cell['family'], 'case': case, 'arm': cell['arm'], 'mode': cell['mode'],
                     'model': cell['model'], 'repeat': rep, 'healthy': h,
                     'cause_pass': None if h or not s else bool(o.get('cause')),
                     'healthy_outcome': o.get('outcome') if h else None,
                     'located': (s.get('facts') or {}).get('located') if s else None,
                     'calls': e.get('calls'), 'calls_no_guidance': e.get('calls_no_guidance'),
                     'cost_usd': meta.get('cost_usd'), 'seconds': meta.get('seconds'),
                     'exit': meta.get('exit'), 'error': meta.get('error') or (s.get('error') if s else 'not scored'),
                     'scorer_usd': (s.get('usage') or {}).get('cost_usd')})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='results folder of the batch (run.py --out)')
    ap.add_argument('--work', required=True, help='where data/pools.tar.gz was unpacked and tree.py built roots/')
    ap.add_argument('--roots', help='tree.py output (default WORK/roots)')
    ap.add_argument('--real-root', help='family C: the prepared root of real MFX logs')
    ap.add_argument('--views', help='family C: where the per-case root views go (default WORK/roots/real)')
    ap.add_argument('--skills', help='the psana-daq skills folder (arms skills, both)')
    ap.add_argument('--map', help='the folder holding hutch-resources/ (arms map, both)')
    ap.add_argument('--cell', action='append', default=[], help='FAMILY/ARM[/MODEL[/CASES[/REPEATS]]] (repeatable)')
    ap.add_argument('--cells', help='a JSON list of cells')
    ap.add_argument('--model', default='default', help="cells' model when not given (default %(default)s)")
    ap.add_argument('--cases', default='all', help="cells' cases when not given (default %(default)s)")
    ap.add_argument('--repeats', type=int, default=1, help="cells' repeats when not given (default %(default)s)")
    ap.add_argument('--jobs', type=int, default=2, help='agents (and later scorer calls) at once (default %(default)s)')
    ap.add_argument('--resume', action='store_true', help='keep runs that already finished')
    ap.add_argument('--budget-left', type=float, help='refuse to start if the projected agent+scorer usage exceeds this (USD)')
    ap.add_argument('--agent-usd', type=float, help='per-run agent estimate (USD), instead of the table and OUT')
    ap.add_argument('--scorer-usd', type=float, help='per-run scorer estimate (USD, default %.2f)' % SCORER_USD)
    ap.add_argument('--timeout', type=int, default=1800, help='seconds per run (run.py --timeout)')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and the projection, run nothing')
    ap.add_argument('--no-score', action='store_true', help='run the agents only')
    ap.add_argument('--catalog', default=os.path.join(HERE, 'catalog.json'))
    ap.add_argument('--cases-v3', default=os.path.join(HERE, 'cases_v3.json'))
    ap.add_argument('--cases-real', default=os.path.join(HERE, 'cases_real.json'))
    ap.add_argument('--keys', default=os.path.join(HERE, 'keys_v3.json'))
    ap.add_argument('--agent-cmd')
    ap.add_argument('--no-sandbox', action='store_true')
    ap.add_argument('--expose', action='append', default=[])
    ap.add_argument('--extract-cmd')
    ap.add_argument('--judge-cmd')
    a = ap.parse_args(argv)
    a.out, a.work = os.path.abspath(a.out), os.path.abspath(a.work)
    a.views = os.path.abspath(a.views or os.path.join(a.work, 'roots', 'real'))
    tables = {'v3': read_json(a.cases_v3), 'real': read_json(a.cases_real)}
    raw = [parse_cell(c, a) for c in a.cell] + (read_json(a.cells) if a.cells else [])
    if not raw:
        ap.error('no cells: give --cell or --cells')
    cells = [normalize(c, tables) for c in raw]
    for c in cells:
        if c['arm'] in ('skills', 'both') and not a.skills or c['arm'] in ('map', 'both') and not a.map:
            ap.error('cell %s needs --skills and/or --map' % c['folder'])
        if c['family'] == 'C' and not a.real_root:
            ap.error('family C needs --real-root')
    for k in ('skills', 'map', 'real_root'):
        if getattr(a, k):
            setattr(a, k, os.path.abspath(getattr(a, k)))
    todo = plan(cells)
    pending = [t for t in todo if not (a.resume and finished(os.path.join(a.out, t[3])))]
    est, scorer = estimate(a, [t[0]['model'] for t in pending])
    projected = sum(est[t[0]['model']][0] + scorer for t in pending)
    print('cells:')
    for c in cells:
        print('  %-24s mode %s control %-8s cases %d x %d repeats' % (c['folder'], c['mode'], c['control'] or '-', len(c['cases']), c['repeats']))
    for model, (usd, why) in sorted(est.items()):
        print('per-run estimate: model %-8s agent $%.3f (%s) + scorer $%.3f' % (model, usd, why, scorer))
    print('runs: %d in the batch, %d to do; projected usage $%.2f; budget left %s'
          % (len(todo), len(pending), projected, '$%.2f' % a.budget_left if a.budget_left is not None else 'not given'))
    sys.stdout.flush()
    if a.dry_run:
        return 0
    if a.budget_left is None:
        print('refusing to start: give --budget-left (USD)')
        return 2
    if projected > a.budget_left:
        print('refusing to start: projected $%.2f exceeds the budget left $%.2f' % (projected, a.budget_left))
        return 2
    os.makedirs(a.out, exist_ok=True)
    for c in cells:                                   # family-C views: built once, before any agent starts
        if c['family'] == 'C':
            for cid in c['cases']:
                spec = [x for x in tables['real']['cases'] if x['id'] == cid][0]
                real_mfx.build_view(a.real_root, spec, real_mfx.case_now(tables['real'], spec), a.views)
    lock, t0 = threading.Lock(), time.time()

    def one(t):
        cell, case, rep, rel = t
        log = os.path.join(a.out, cell['folder'] + '.log')
        p = subprocess.run(run_cmd(a, cell, case, rep), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        with lock:
            with open(log, 'a') as f:
                f.write(p.stdout)
            line = [l for l in p.stdout.splitlines() if l.startswith(cell['folder'])]
            print('[%5.0fs] %s' % (time.time() - t0, line[0] if line else '%s %s r%d: run.py exit %d %s' % (
                cell['folder'], case, rep, p.returncode, p.stdout.strip().splitlines()[-1:] if p.stdout else '')))
            sys.stdout.flush()
        return p.returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        codes = list(ex.map(one, todo))
    print('agents done: %d runs, %d run.py failures' % (len(todo), sum(1 for c in codes if c)))
    if a.no_score:
        return 0
    scored, evid, smeta = score_and_evidence(a)
    rows = rows_for(a, todo, tables, scored, evid)
    with open(os.path.join(a.out, 'rows.json'), 'w') as f:
        json.dump(rows, f, indent=1)
    usage = {'runs': len(rows), 'agent_usd': round(sum(r['cost_usd'] or 0 for r in rows), 4),
             'scorer_usd': round(sum(r['scorer_usd'] or 0 for r in rows), 4),
             'scorer_fresh_usd_this_call': smeta.get('fresh_cost_usd_this_run'),
             'scorer_usd_all_rows_in_out': smeta.get('scorer_cost_usd'), 'projected_usd': round(projected, 4),
             'estimate_per_run': dict((m, v[0]) for m, v in est.items()), 'scorer_estimate_per_run': scorer}
    usage['total_usd'] = round(usage['agent_usd'] + usage['scorer_usd'], 4)
    with open(os.path.join(a.out, 'usage.json'), 'w') as f:
        json.dump(usage, f, indent=1)
    print('%-34s %-20s %-7s %-6s %-6s %-8s %-6s %-20s' % ('run', 'case', 'exit', 'secs', 'usd', 'located', 'calls', 'cause / healthy'))
    for r in rows:
        print('%-34s %-20s %-7s %-6s %-6s %-8s %-6s %-20s' % (
            r['run_id'], r['case'], r['exit'], r['seconds'], '%.3f' % (r['cost_usd'] or 0), r['located'], r['calls'],
            r['healthy_outcome'] if r['healthy'] else ('PASS' if r['cause_pass'] else 'fail' if r['cause_pass'] is False else '-')))
    print('usage: %s' % json.dumps(usage))
    print('rows: %s  (python3 verdict.py %s)' % (os.path.join(a.out, 'rows.json'), os.path.join(a.out, 'rows.json')))
    return 0 if not any(codes) else 1


if __name__ == '__main__':
    sys.exit(main())
