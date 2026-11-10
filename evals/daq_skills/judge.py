"""Have a model read each report against its answer key and give a verdict.

    python3 judge.py --results RESULTS_DIR [--jobs N] [--model sonnet] [--redo]
    python3 judge.py --calibrate tests/judge_set.json [--model sonnet]

grade.py's keyword check reads words, so it can pass a report that mentions the right
words while blaming something else, and fail a right report in unusual wording.  It also
reads a templated report (one section) and a free-form one (the whole message)
differently.  The judge applies one rubric to every report.  It sees the question, the
answer key and the report, never the transcript, and writes judge.json next to final.md:
  {"verdict": correct|partial|wrong|unknown|false-alarm, "component", "right_launch", "reason"}

A judge is itself a model and can be wrong.  --calibrate runs it on a file of reports
whose verdicts were set by hand and prints how many it gets right, and which it misses.
Run that whenever the rubric or the judge model changes, and quote its result with any
score that relies on the judge.

Each report is judged --votes times (default 3) and the majority verdict is kept, because a
single judgement of a long report varies from call to call.  Each judgement is one headless
'claude -p' call (no tools needed).  Standard library only.
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile

RUBRIC = """You are grading a DAQ incident report against an answer key. Judge the meaning, not the wording.

QUESTION the report's author was asked:
{question}

ANSWER KEY (what really happened; the author never saw it):
{key}

REPORT:
<<<
{report}
>>>

Give exactly one verdict.

When the key names one fault:
- "correct": the report's main conclusion identifies the key's root cause: the same failing component, the same stage and the same mechanism (the specific error). All three must match. Extra correct detail, caveats about what the logs cannot show, and side issues do not change this. Different words for the same thing are fine.
- The stage is the DAQ transition or state in which the fault happened (startup, rollcall, alloc, connect, configure, enable, running, disable, ...). A report that puts the fault in a different stage than the key is at most "partial", even with the right component and mechanism.
- When the key names a launch, the report must be about that launch. If the report clearly places the failure in a launch that started at a different local time (more than a few minutes from the key's), it is "wrong", even if its mechanism matches. If the report gives no launch or time at all, do not hold that against it.
- "partial": the main conclusion has the right component and stage but not the mechanism (it stops at "did not respond" or "timed out"); or the right component and mechanism but the wrong stage; or it gives the true cause only as one of several possibilities without ranking it first.
- "wrong": the main conclusion blames a different component or mechanism; or it is about a different launch than the key's; or it mentions the true cause only to dismiss it.
- "unknown": the report says it could not determine the cause and does not assert a wrong one.
- When the key's mechanism is itself a hang (the component went silent with no error of its own), a report that says the component hung or stopped responding during that stage, with no error, has the mechanism. It need not say why it hung.

When the key says NO FAULT:
- "correct": the report concludes that the DAQ session and its data taking worked in the launches asked about. It may also report the key's side issues, even prominently (for example a crash at shutdown, after the run had ended), as long as it says the run itself was clean.
- "false-alarm": the report presents something as a failure of the DAQ session or of data taking that the key does not.

When the key lists several failed launches:
- "correct": the report lists every one of them with the right cause for each and no launch that did not fail.
- "partial": it has at least half of them with the right causes, or all of them with some causes missing or wrong.
- "wrong": anything less.

Reply with only a JSON object:
{{"verdict": "...", "component": "<the component the report blames, or none>", "right_launch": true or false or null, "reason": "<at most 30 words>"}}"""


def key_text(key):
    f = key.get('fault')
    lines = []
    if key.get('launches'):
        lines.append('%d launches failed:' % len(key['launches']))
        for l in key['launches']:
            lines.append('- launch %s: %s' % (l['prefix'], l['cause']))
    elif f:
        lines.append('Root cause: ' + f['summary'])
        lines.append('Failing component: ' + ', '.join(f.get('component', [])))
        lines.append('Stage: ' + ', '.join(f.get('transition', [])[:4]))
    else:
        lines.append('NO FAULT in the launches the question asks about.')
    if key.get('sessions') and not key.get('launches'):
        lines.append('Launch(es) concerned: ' + '; '.join('started on day %s at %s local time (PST, UTC-8), log prefix %s'
                                                      % (p[:2], p[3:], p) for p in key['sessions']))
    if key.get('independent'):
        lines.append('Side issues that are present but are not the cause: ' + ', '.join(key['independent']))
    return '\n'.join(lines)


def parse(text):
    m = re.search(r'\{.*\}', text or '', re.S)
    d = None
    if m:
        try:
            d = json.loads(m.group(0))
        except ValueError:
            d = None
    if not isinstance(d, dict):                      # e.g. an unescaped quote in the reason
        v = re.search(r'"verdict"\s*:\s*"([A-Za-z_ -]+)"', text or '')
        if not v:
            return None
        launch = re.search(r'"right_launch"\s*:\s*(true|false|null)', text)
        d = {'verdict': v.group(1), 'right_launch': {'true': True, 'false': False}.get(launch.group(1)) if launch else None,
             'reason': (re.search(r'"reason"\s*:\s*"(.*)', text, re.S) or [None, ''])[1][:200]}
    v = str(d.get('verdict', '')).lower().replace('_', '-').replace(' ', '-')
    if v not in ('correct', 'partial', 'wrong', 'unknown', 'false-alarm'):
        return None
    if d.get('right_launch') is False and v in ('correct', 'partial'):
        v = 'wrong'                                   # the rubric's rule, applied here so it cannot be softened
    d['verdict'] = v
    return d


def judge(question, key, report, model, cmd=None, votes=1):
    """The majority verdict of 'votes' independent judgements (ties go to the first)."""
    got = [judge_once(question, key, report, model, cmd) for _ in range(votes)]
    good = [g for g in got if g.get('verdict')]
    if not good:
        return got[0]
    tally = {}
    for g in good:
        tally[g['verdict']] = tally.get(g['verdict'], 0) + 1
    best = max(tally, key=lambda v: (tally[v], -[g['verdict'] for g in good].index(v)))
    out = dict(next(g for g in good if g['verdict'] == best))
    out.update(votes=[g['verdict'] for g in good], cost_usd=sum(g.get('cost_usd') or 0 for g in good))
    return out


def judge_once(question, key, report, model, cmd=None):
    prompt = RUBRIC.format(question=question, key=key_text(key), report=report[:24000])
    argv = cmd or ['claude', '-p', '--output-format', 'json', '--model', model, '--setting-sources', 'project',
                   '--strict-mcp-config']
    with tempfile.TemporaryDirectory(prefix='judge-') as cwd:
        for attempt in range(2):
            p = subprocess.run(argv, input=prompt, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                               universal_newlines=True, timeout=600)
            try:
                res = json.loads(p.stdout)
            except ValueError:
                res = {'result': p.stdout}
            d = parse(res.get('result') if isinstance(res, dict) else None)
            if d:
                d.update(model=model, cost_usd=res.get('total_cost_usd'))
                return d
    return {'verdict': None, 'error': (p.stdout or p.stderr)[:300], 'model': model}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--catalog', default=os.path.join(here, 'catalog.json'))
    ap.add_argument('--results')
    ap.add_argument('--calibrate', help='a JSON list of {id, question, key, report, expect}')
    ap.add_argument('--model', default='sonnet')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--redo', action='store_true')
    ap.add_argument('--votes', type=int, default=3, help='judgements per report; the majority wins (default %(default)d)')
    ap.add_argument('--out', help='with --calibrate: write the judgements here')
    ap.add_argument('--judge-cmd', help='replace the claude command (tests)')
    a = ap.parse_args(argv)
    cmd = a.judge_cmd.split() if a.judge_cmd else None
    if a.calibrate:
        items = json.load(open(a.calibrate))
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            got = list(ex.map(lambda it: judge(it['question'], it['key'], it['report'], a.model, cmd, a.votes), items))
        ok = 0
        for it, g in zip(items, got):
            hit = g.get('verdict') == it['expect']
            ok += hit
            print('%-4s %-28s expect %-11s judge %-11s %s' % ('ok' if hit else 'MISS', it['id'], it['expect'], g.get('verdict'),
                                                             (g.get('reason') or g.get('error') or '')[:90]))
        print('\njudge %s agrees with the hand labels on %d of %d' % (a.model, ok, len(items)))
        if a.out:
            json.dump([dict(id=it['id'], expect=it['expect'], **g) for it, g in zip(items, got)], open(a.out, 'w'), indent=1)
        return 0 if ok == len(items) else 1
    cat = json.load(open(a.catalog))
    cases = {c['id']: c for c in cat['cases']}
    todo = []
    for arm in sorted(os.listdir(a.results)):
        for name in sorted(os.listdir(os.path.join(a.results, arm))) if os.path.isdir(os.path.join(a.results, arm)) else []:
            d = os.path.join(a.results, arm, name)
            mp = os.path.join(d, 'meta.json')
            if not os.path.exists(mp):
                continue
            m = json.load(open(mp))
            if m.get('dry_run') or m.get('error') or m['case'] not in cases or cases[m['case']]['set'] == 'disputed':
                continue
            if os.path.exists(os.path.join(d, 'judge.json')) and not a.redo:
                continue
            todo.append((d, cases[m['case']]))

    def one(job):
        d, c = job
        g = judge(c['question'], c['key'], open(os.path.join(d, 'final.md')).read(), a.model, cmd, a.votes)
        if g.get('verdict'):
            json.dump(g, open(os.path.join(d, 'judge.json'), 'w'), indent=1)
        return d, c['id'], g

    bad = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for d, cid, g in ex.map(one, todo):
            bad += not g.get('verdict')
            print('%-12s %-26s %-11s %s' % (os.path.basename(os.path.dirname(d)), cid, g.get('verdict'),
                                           (g.get('reason') or g.get('error') or '')[:90]))
            sys.stdout.flush()
    print('%d judged, %d failed' % (len(todo), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
