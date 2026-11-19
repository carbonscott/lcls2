"""Score DAQ-skill eval reports fact by fact against keys_v3.json (the v3 scorer).

    python3 score.py --results RESULTS_DIR --out scored.json [--summary scored.txt] [--jobs 2] [--model sonnet]
                     [--cache DIR] [--votes 3] [--only ID ...] [--limit N] [--quiet-ids FILE]
    python3 score.py --report final.md --case CASE           # one report, record printed
    python3 score.py --traps tests/judge_set.json             # the hand-labelled trap reports

RESULTS_DIR is run.py's layout: <arm>/<run>/{meta.json, final.md}.  A run's id is <arm>/<run>.
Each report is scored in four steps; only steps 1 and 3 call a model.

  1. EXTRACT  one model call sees ONLY the report (no key, no arm, no question) and returns a
              record: the verdict (fault | no-fault | unsure), the launches it names, its
              problems, each with a role (cause | side-issue | consequence | possible), the
              component, the stage and a verbatim quote of the mechanism, and its asks to the
              operator.  Cached by the report's sha256, so a re-run costs nothing.
  2. FACTS    scripts compare the record with the key: launch (only where the pool holds many
              launches), component and stage by aliases, and 'located': the report names the
              keyed launch (its start stamp, a log-file prefix, or a time that falls in that
              launch, or within 2 minutes of its start when no launch holds it).
  3. MECHANISM the only judged fact.  A model sees the extracted mechanism quote and the key's
              accepted and near-miss lists, nothing else, --votes times (default 3); the
              majority of accepted | near-miss | other wins (no majority: 'split').
  4. OUTCOME  fault case: Cause passes iff launch (where keyed), component, stage and
              mechanism (majority 'accepted') all pass; also reported strict (all votes
              accepted) and lenient (any vote).  Healthy case: clean | benign-defect-noted |
              false-alarm.  The day-count case passes iff every failed launch is listed with
              all its facts and no healthy launch is called failed.

Both model steps are headless 'claude -p' calls with no tools and a one-line system prompt;
--extract-cmd and --judge-cmd replace the command (tests): the prompt arrives on stdin and the
program prints {"result": "<text>", "total_cost_usd": x}.  At most --jobs calls run at once.
Standard library only.
"""

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM = 'You annotate DAQ incident reports for a scoring script. Reply with one JSON object and nothing else.'

EXTRACT_PROMPT = """You turn one DAQ incident report into a JSON record. A script will compare the record with an answer key that you do not see, so copy what the report says. Do not judge whether the report is right and do not add your own analysis.

The report answers an operator's question about LCLS-II DAQ logs. A "launch" is one start of the DAQ processes; its log files are named DD_HH:MM:SS_<host>:<process>.log, and DD_HH:MM:SS is the launch's start stamp.

REPORT:
<<<
{report}
>>>

Return one JSON object with these keys.

"verdict_kind": the report's answer about the DAQ session(s) it was asked about:
  "fault": it concludes that something failed or went wrong that harmed the session or its data taking (a transition failed, the DAQ could not allocate, connect, configure or run, data was lost or damaged);
  "no-fault": it concludes that the session and its data taking worked, even if it lists problems it calls harmless, cosmetic, unrelated, or at shutdown after the run ended (such a report may still open with "yes, one thing went wrong");
  "unsure": it says it cannot tell.

"launches": every launch the report names, in the report's order, each {{"time": "HH:MM:SS or HH:MM as written", "date": "YYYY-MM-DD or null", "tz": "local" | "UTC" | "unstated", "status": "failed" | "ok" | "unclear"}}. Use the launch's start stamp or log-file prefix when the report gives one, else the earliest time it gives for that launch. PST, PT and Pacific are "local".

"problems": the problems the report states, each {{"role": ..., "launch_time": "HH:MM:SS or null", "tz": "local" | "UTC" | "unstated", "component": "...", "stage": "...", "mechanism": "..."}}.
  role "cause": the report's conclusion about what failed first, or caused the failure (its root cause). Put the main one first. A report about several failed launches has one "cause" per failed launch, even where it groups launches under one cause (repeat the cause for each launch, with that launch's time).
  role "side-issue": a problem it reports but says did not cause the failure or did not affect data taking (benign, cosmetic, at shutdown, a separate bug, unrelated).
  role "consequence": something it says happened because of a cause.
  role "possible": a cause it offers only as a possibility ranked below its main conclusion, or raises and rejects.
  "component": the process or device that failed, as the report names it (for example tt_0, teb0, meb0, control, pvcam_0); the name only. If the report blames several components together without saying which one failed first, give every one it blames, joined by " + ".
  "stage": the DAQ transition or state in which that component failed, as the report says (for example startup, rollcall, alloc, connect, configure, beginrun, enable, running, disable, unconfigure, disconnect, shutdown); "" if it does not say.
  "mechanism": verbatim quotes from the report, at most 4 sentences or table cells: first the report's own statement of what failed and why (its headline or conclusion for this problem); then, if it is elsewhere, the sentence that gives the specific error for it: the error message or log line the report quotes, or the exact item that failed (a register, PV, variable name, link or signal). Copy exactly. "" if the report gives none.
  Leave out what the report calls normal operation.

"asks_operator": questions the report asks the operator, or checks it says a person must make (short phrases); [] if none.

"confidence": the confidence the report states ("high", "medium" or "low"), or null.

Reply with the JSON object only."""

JUDGE_PROMPT = """You compare statements from DAQ incident reports with an answer key's closed lists. Judge the meaning, not the wording.

For each item, STATEMENT is what a report says is the specific error or reason for a failure. ACCEPTED lists statements of the true mechanism. NEAR-MISSES lists statements that sound close but are incomplete or wrong.

{items}

Give each item one verdict:
- "accepted": the statement asserts the specific error or reason of at least one ACCEPTED entry. Other words, more detail, extra correct context and caveats about what the logs cannot show are fine; it need not repeat everything in the entry.
- "near-miss": the statement matches a NEAR-MISS entry, or gives only the symptom or a consequence and stops short of every ACCEPTED entry.
- "other": the statement gives a different mechanism, or none.
A statement that mentions an accepted mechanism only to doubt or reject it is not "accepted". A statement that gives an accepted entry's error only as a symptom, and blames the failure on what a NEAR-MISS entry names, is "near-miss". A statement that blames an accepted mechanism and adds its own further explanation of why it happened is still "accepted", unless that explanation is a NEAR-MISS entry.

Reply with only a JSON object: {{"items": [{{"item": 1, "verdict": "accepted" | "near-miss" | "other", "matched": "A1 | N2 | none", "reason": "<at most 20 words>"}}]}}"""

ITEM = """ITEM {n}
STATEMENT:
<<<
{statement}
>>>
ACCEPTED:
{accepted}
NEAR-MISSES:
{near}"""

VERDICTS = ('accepted', 'near-miss', 'other')
HEALTHY_OUTCOMES = ('clean', 'benign-defect-noted', 'false-alarm')


def sha(text):
    return hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()


def read_text(path):
    with open(path, errors='replace') as f:
        return f.read()


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_text(path, text):
    with open(path, 'w') as f:
        f.write(text)


def write_json(path, obj, indent=1):
    """Write through a temporary file, so a reader never sees half a file."""
    tmp = '%s.tmp%d' % (path, threading.get_ident())
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=indent)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# model calls


class Caller:
    """Runs one headless model call; caches by prompt; counts calls and usage (thread-safe)."""

    def __init__(self, model='sonnet', cmd=None, cache=None, jobs=2):
        self.model, self.cmd, self.cache = model, cmd, cache
        self.lock = threading.Lock()
        self.sem = threading.BoundedSemaphore(max(1, jobs))
        self.fresh_calls, self.fresh_cost = 0, 0.0

    def argv(self):
        return self.cmd or ['claude', '-p', '--output-format', 'json', '--model', self.model, '--setting-sources', 'project',
                            '--strict-mcp-config', '--tools', '', '--system-prompt', SYSTEM]

    def call(self, prompt, kind, tag='', name=None):
        """{'text', 'cost_usd', 'model', 'cached', 'error'} for one call.  Cached in CACHE/<kind>/<name>.json
        (name defaults to a hash of the prompt); an entry made from another prompt or model is a miss."""
        psha = sha('%s|%s|%s' % (self.model, tag, prompt))
        path = os.path.join(self.cache, kind, (name or psha) + '.json') if self.cache else None
        if path and os.path.exists(path):
            try:
                d = read_json(path)
            except ValueError:
                d = {}
            if d.get('prompt_sha256') == psha:
                d['cached'] = True
                return d
        d = {'error': None, 'text': None, 'cost_usd': None, 'model': None, 'prompt_sha256': psha}
        with self.sem, tempfile.TemporaryDirectory(prefix='score-') as cwd:
            try:
                p = subprocess.run(self.argv(), input=prompt, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                                   universal_newlines=True, timeout=600)
                out, err = p.stdout, p.stderr
            except subprocess.TimeoutExpired:
                out, err = '', 'timeout'
        try:
            res = json.loads(out)
        except ValueError:
            res = {'result': out}
        if not isinstance(res, dict):
            res = {'result': out}
        d['text'] = res.get('result') if isinstance(res.get('result'), str) else None
        d['cost_usd'] = res.get('total_cost_usd')
        mu = res.get('modelUsage')
        d['model'] = ','.join(sorted(mu)) if isinstance(mu, dict) and mu else (res.get('model') or self.model)
        if not d['text'] or res.get('is_error'):
            d['error'] = (err or out or 'no output')[:300]
        with self.lock:
            self.fresh_calls += 1
            self.fresh_cost += d['cost_usd'] or 0
        if path and not d['error']:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_json(path, d)
        d['cached'] = False
        return d


def first_json(text):
    """The first JSON object in text, or None."""
    if not text:
        return None
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
    cands = [m.group(1)] if m else []
    i = text.find('{')
    if i >= 0:
        cands.append(text[i:text.rfind('}') + 1])
    for c in cands:
        try:
            d = json.loads(c)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    return None


def call_json(caller, prompt, kind, tag='', tries=2, name=None):
    """(parsed dict or None, [call records]).  A reply that is not JSON is retried once."""
    calls = []
    for t in range(tries):
        suffix = '' if t == 0 else '-retry%d' % t
        d = caller.call(prompt, kind, tag + suffix, name=(name + suffix) if name else None)
        calls.append({k: d.get(k) for k in ('cost_usd', 'model', 'cached', 'error')})
        got = first_json(d.get('text'))
        if got is not None:
            return got, calls
    return None, calls


# ---------------------------------------------------------------------------
# step 1: extract


def normalize_record(r):
    """Fill defaults so the scripts below never meet a missing field."""
    r = dict(r or {})
    vk = str(r.get('verdict_kind') or '').lower().replace('_', '-').replace(' ', '-')
    r['verdict_kind'] = vk if vk in ('fault', 'no-fault', 'unsure') else 'unsure'
    r['launches'] = [x for x in (r.get('launches') or []) if isinstance(x, dict)]
    probs = []
    for p in r.get('problems') or []:
        if not isinstance(p, dict):
            continue
        p = {k: ('' if p.get(k) is None else str(p.get(k))) for k in ('role', 'launch_time', 'tz', 'component', 'stage', 'mechanism')}
        p['role'] = p['role'].lower().replace('_', '-').replace(' ', '-')
        probs.append(p)
    r['problems'] = probs
    r['asks_operator'] = [str(x) for x in (r.get('asks_operator') or [])]
    return r


def extract(caller, report):
    prompt = EXTRACT_PROMPT.format(report=report[:40000])
    d, calls = call_json(caller, prompt, 'extract', name=sha(report))      # cached by the report's sha256
    rec = normalize_record(d) if d is not None else None
    return rec, calls


# ---------------------------------------------------------------------------
# step 2: scripted facts

TIME = re.compile(r'(?<!\d)(\d{1,2}):(\d\d)(?::(\d\d))?(?!\d)')
PREFIX = re.compile(r'(?<!\d)(\d\d)_(\d\d:\d\d:\d\d)(?!\d)')


def parse_dt(s):
    return datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')


def to_local(time_s, date_s, tz, default_date, offset_h=-8):
    """A datetime in local time from a report's time, or None."""
    if not time_s:
        return None
    m = PREFIX.search(time_s)
    day = None
    if m:
        day, time_s = m.group(1), m.group(2)
    m = TIME.search(time_s)
    if not m:
        return None
    hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if hh > 23 or mm > 59 or ss > 59:
        return None
    date = None
    if date_s and re.match(r'\d{4}-\d\d-\d\d', str(date_s)):
        date = str(date_s)[:10]
    elif default_date:
        date = default_date
        if day:
            date = default_date[:8] + day
    if not date:
        return None
    try:
        dt = datetime.datetime.strptime('%s %02d:%02d:%02d' % (date, hh, mm, ss), '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None
    if str(tz).upper() == 'UTC' or re.search(r'\bUTC\b|\bZ$', time_s):
        dt += datetime.timedelta(hours=offset_h)
        if not date_s and default_date and dt.strftime('%Y-%m-%d') != default_date:
            # a UTC time with no date: assume it is on the day of the case
            dt = dt.replace(year=int(default_date[:4]), month=int(default_date[5:7]), day=int(default_date[8:10]))
    return dt


def pool_launches(keys, key):
    """[(prefix, start dt, last dt)] of every launch in the case's pool."""
    rows = keys.get('pools', {}).get(key['pool'])
    if rows is None:
        rows = [[l['prefix'], l['start'], l['last']] for l in key.get('launches', [])]
    return [(p, parse_dt(s), parse_dt(e)) for p, s, e in rows]


def resolve(dt, launches, slack=5, near=120):
    """The prefix of the launch a time belongs to: the launch whose logs span it, else the
    launch that started nearest to it within 'near' seconds, else None."""
    if dt is None:
        return None
    for p, s, e in launches:
        if s - datetime.timedelta(seconds=slack) <= dt <= e + datetime.timedelta(seconds=slack):
            return p
    best = min(launches, key=lambda l: abs((l[1] - dt).total_seconds()), default=None)
    if best and abs((best[1] - dt).total_seconds()) <= near:
        return best[0]
    return None


def default_date(key):
    if key.get('launches'):
        return key['launches'][0]['start'][:10]
    m = re.search(r'\d{4}-\d\d-\d\d', key.get('question', ''))
    return m.group(0) if m else None


def named_launches(key, keys, rec, text):
    """The pool launches the report names: by prefix or start stamp in its text, or by a time
    in the extracted record."""
    launches = pool_launches(keys, key)
    dd, off = default_date(key), keys.get('tz_offset_hours', -8)
    named = set()
    for p, s, e in launches:
        if p in text or re.search(r'(?<![\d:])%s(?![\d:])' % re.escape(p[3:]), text):
            named.add(p)
    for l in (rec or {}).get('launches', []):
        r = resolve(to_local(str(l.get('time') or ''), l.get('date'), l.get('tz'), dd, off), launches)
        if r:
            named.add(r)
    for pr in (rec or {}).get('problems', []):
        r = resolve(to_local(pr.get('launch_time'), None, pr.get('tz'), dd, off), launches)
        if r:
            named.add(r)
    return named


def norm(s):
    return re.sub(r'[`*"\']', '', str(s or '')).strip()


def alias_hits(aliases, text):
    """[(position, alias)] of whole-word, case-insensitive matches."""
    out = []
    for a in aliases:
        m = re.search(r'(?<![\w])' + re.escape(a.lower()) + r'(?![\w])', text.lower())
        if m:
            out.append((m.start(), a))
    return sorted(out)


def component_ok(kc, said):
    """The report blames the keyed component: an alias matches and no 'not' alias comes before it.
    Several components blamed together ('a + b') pass only if every one is the keyed component."""
    parts = [p for p in norm(said).split(' + ') if p.strip()]
    if not parts:
        return False
    for part in parts:
        pos = alias_hits(kc['aliases'], part)
        if not pos:
            return False
        neg = alias_hits(kc.get('not', []), part)
        if neg and neg[0][0] < pos[0][0]:
            return False
    return True


def stage_ok(ks, said):
    return bool(alias_hits(ks['aliases'], norm(said)))


def causes(rec):
    return [p for p in rec['problems'] if p['role'] == 'cause']


def quote_found(quote, text):
    q = re.sub(r'\s+', ' ', norm(quote)).lower()
    t = re.sub(r'\s+', ' ', norm(text)).lower()
    return bool(q) and q[:120] in t


# ---------------------------------------------------------------------------
# step 3: mechanism judge


def judge_items(caller, items, votes):
    """items: [{'statement', 'mechanism': {accepted, near_miss}}] -> per item
    {'votes': [...], 'verdict': majority or 'split', 'strict', 'lenient'}, plus call records."""
    out = [{'votes': [], 'matched': []} for _ in items]
    todo = [i for i, it in enumerate(items) if norm(it['statement'])]
    calls = []
    if todo:
        text = '\n\n'.join(ITEM.format(n=k + 1, statement=items[i]['statement'][:3000],
                                       accepted='\n'.join(' A%d. %s' % (j + 1, s) for j, s in enumerate(items[i]['mechanism']['accepted'])),
                                       near='\n'.join(' N%d. %s' % (j + 1, s) for j, s in enumerate(items[i]['mechanism']['near_miss'])))
                           for k, i in enumerate(todo))
        prompt = JUDGE_PROMPT.format(items=text)
        for v in range(votes):
            d, c = call_json(caller, prompt, 'judge', tag='vote%d' % v)
            calls += c
            got = {}
            for x in (d or {}).get('items') or []:
                if isinstance(x, dict):
                    try:
                        got[int(x.get('item'))] = x
                    except (TypeError, ValueError):
                        pass
            for k, i in enumerate(todo):
                x = got.get(k + 1) or {}
                vd = str(x.get('verdict', '')).lower().replace('_', '-').replace(' ', '-')
                out[i]['votes'].append(vd if vd in VERDICTS else 'error')
                out[i]['matched'].append(x.get('matched'))
    for i, o in enumerate(out):
        vs = [v for v in o['votes'] if v in VERDICTS]
        if i not in todo:
            o.update(verdict='none', strict=False, lenient=False)
            continue
        tally = {v: vs.count(v) for v in VERDICTS}
        top = max(VERDICTS, key=lambda v: tally[v])
        o['verdict'] = top if tally[top] * 2 > len(o['votes']) else 'split'
        o['strict'] = bool(o['votes']) and all(v == 'accepted' for v in o['votes'])
        o['lenient'] = 'accepted' in o['votes']
    return out, calls


# ---------------------------------------------------------------------------
# step 4: per kind of case


def score_fault(key, keys, rec, text, caller, votes):
    named = named_launches(key, keys, rec, text)
    launches = pool_launches(keys, key)
    dd, off = default_date(key), keys.get('tz_offset_hours', -8)
    cs = causes(rec)
    pick, how = (cs[0] if cs else None), 'main cause'
    if key.get('launch_keyed') and cs:
        for c in cs:                                  # the cause the report gives for the keyed launch, if any
            if resolve(to_local(c['launch_time'], None, c['tz'], dd, off), launches) == key['fault_launch']:
                pick, how = c, 'cause of the keyed launch'
                break
    if pick is None and key.get('side_issue_ok'):
        side = [p for p in rec['problems'] if component_ok(key['component'], p['component'])]
        if side:
            pick, how = side[0], 'non-fatal problem (the key allows it)'
    f = {'cause_found': pick is not None, 'picked': how if pick else None, 'verdict_kind': rec['verdict_kind'],
         'affected': rec['verdict_kind'] == 'fault', 'named_launches': sorted(named)}
    f['located'] = all(l['prefix'] in named for l in key['launches']) if key['launches'] else None
    if key.get('launch_keyed'):
        at = resolve(to_local(pick['launch_time'], None, pick['tz'], dd, off), launches) if pick else None
        f['cause_launch'] = at
        ok = (at == key['fault_launch']) if at else (key['fault_launch'] in named and pick is not None)
        need = key.get('required_launches') or []
        f['required_named'] = [p for p in need if p in named]
        f['launch'] = bool(ok) and len(f['required_named']) == len(need)
    else:
        f['launch'] = None                            # one launch in the pool: not scored
    f['component_said'] = pick['component'] if pick else None
    f['stage_said'] = pick['stage'] if pick else None
    f['component'] = bool(pick) and component_ok(key['component'], pick['component'])
    f['stage'] = bool(pick) and stage_ok(key['stage'], pick['stage'])
    f['mechanism_quote'] = pick['mechanism'] if pick else ''
    f['quote_in_report'] = quote_found(f['mechanism_quote'], text) if pick else None
    mech, calls = judge_items(caller, [{'statement': f['mechanism_quote'], 'mechanism': key['mechanism']}], votes)
    m = mech[0]
    base = f['launch'] is not False and f['component'] and f['stage']
    out = {'kind': 'fault', 'cause': bool(base and m['verdict'] == 'accepted'),
           'cause_strict': bool(base and m['strict']), 'cause_lenient': bool(base and m['lenient'])}
    return f, m, out, calls


def score_multi(key, keys, rec, text, caller, votes):
    launches = pool_launches(keys, key)
    dd, off = default_date(key), keys.get('tz_offset_hours', -8)
    named = named_launches(key, keys, rec, text)
    failed = {x['prefix']: x for x in key['failed']}
    got, extra, unplaced = {}, [], 0
    for c in causes(rec):
        at = resolve(to_local(c['launch_time'], None, c['tz'], dd, off), launches)
        if at in failed:
            got.setdefault(at, c)
        elif at:
            extra.append(at)
        else:
            unplaced += 1
    for l in rec['launches']:                         # a launch listed as failed with no cause given
        at = resolve(to_local(str(l.get('time') or ''), l.get('date'), l.get('tz'), dd, off), launches)
        if str(l.get('status')) == 'failed' and at and at not in failed and at not in extra:
            extra.append(at)
    items, per = [], []
    for p, x in failed.items():
        c = got.get(p)
        per.append({'prefix': p, 'family': x['family'], 'found': c is not None,
                    'component': bool(c) and component_ok(key['component'], c['component']),
                    'stage': bool(c) and stage_ok(x['stage'], c['stage']), 'mechanism_quote': c['mechanism'] if c else ''})
        items.append({'statement': c['mechanism'] if c else '', 'mechanism': x['mechanism']})
    mech, calls = judge_items(caller, items, votes)
    for r, m in zip(per, mech):
        r['mechanism'] = m['verdict']
        r['votes'] = m['votes']
        r['pass'] = r['found'] and r['component'] and r['stage'] and m['verdict'] == 'accepted'
        r['pass_strict'] = r['found'] and r['component'] and r['stage'] and m['strict']
        r['pass_lenient'] = r['found'] and r['component'] and r['stage'] and m['lenient']
    f = {'verdict_kind': rec['verdict_kind'], 'affected': rec['verdict_kind'] == 'fault', 'named_launches': sorted(named),
         'located': all(p in named for p in failed), 'located_n': sum(p in named for p in failed),
         'failed_found': sum(r['found'] for r in per), 'extra_failed': sorted(set(extra)), 'unplaced_causes': unplaced,
         'launches': per, 'launch': not extra and all(r['found'] for r in per),
         'component': all(r['component'] for r in per), 'stage': all(r['stage'] for r in per)}
    m = {'verdict': 'accepted' if all(r['mechanism'] == 'accepted' for r in per) else 'not all accepted',
         'per_launch': [r['mechanism'] for r in per], 'n_accepted': sum(r['mechanism'] == 'accepted' for r in per)}
    out = {'kind': 'multi', 'cause': not extra and all(r['pass'] for r in per),
           'cause_strict': not extra and all(r['pass_strict'] for r in per),
           'cause_lenient': not extra and all(r['pass_lenient'] for r in per), 'launches_right': sum(r['pass'] for r in per)}
    return f, m, out, calls


def score_healthy(key, keys, rec, text):
    named = named_launches(key, keys, rec, text)
    cs = causes(rec)
    vk = rec['verdict_kind']
    if vk == 'fault' or (vk == 'unsure' and cs):
        outcome = 'false-alarm'
    elif rec['problems']:
        outcome = 'benign-defect-noted'
    else:
        outcome = 'clean'
    noted = ' | '.join('%s %s %s' % (p['component'], p['stage'], p['mechanism']) for p in rec['problems'])
    benign = [b['id'] for b in key.get('benign', []) if alias_hits(b['aliases'], norm(noted) + ' ' + norm(text))]
    f = {'verdict_kind': vk, 'affected': vk == 'fault', 'unsure': vk == 'unsure', 'named_launches': sorted(named),
         'located': (all(l['prefix'] in named for l in key['launches']) if key['launches'] else None),
         'causes_given': [{'component': c['component'], 'stage': c['stage'], 'mechanism': c['mechanism'][:300]} for c in cs],
         'problems_noted': len(rec['problems']), 'benign_named': benign,
         'known_issue_cited': [n for n in key.get('known_issues', []) if re.search(r'(#|issues/)%d\b' % n, text)]}
    return f, {'verdict': 'n/a'}, {'kind': 'healthy', 'outcome': outcome}, []


def score_report(key, keys, text, caller, votes=3):
    """The scored row for one report: facts, mechanism, outcome, record, calls."""
    rec, xcalls = extract(caller, text)
    row = {'report_sha256': sha(text), 'record': rec, 'calls': {'extract': xcalls, 'judge': []}}
    if rec is None:
        row.update(error='extraction failed', facts={}, mechanism={}, outcome={'kind': key['kind'], 'cause': False}
                   if key['kind'] != 'healthy' else {'kind': 'healthy', 'outcome': None})
        return row
    if key['kind'] == 'healthy':
        f, m, o, jcalls = score_healthy(key, keys, rec, text)
    elif key['kind'] == 'multi':
        f, m, o, jcalls = score_multi(key, keys, rec, text, caller, votes)
    else:
        f, m, o, jcalls = score_fault(key, keys, rec, text, caller, votes)
    row['calls']['judge'] = jcalls
    row.update(facts=f, mechanism=m, outcome=o, asks_operator=rec['asks_operator'], confidence=rec.get('confidence'))
    return row


def usage(row):
    calls = row['calls']['extract'] + row['calls']['judge']
    return {'calls': len(calls), 'cost_usd': round(sum(c.get('cost_usd') or 0 for c in calls), 6),
            'fresh_calls': sum(not c.get('cached') for c in calls),
            'fresh_cost_usd': round(sum(c.get('cost_usd') or 0 for c in calls if not c.get('cached')), 6),
            'models': sorted({c.get('model') for c in calls if c.get('model')})}


# ---------------------------------------------------------------------------
# runs, summary


def load_keys(path):
    return read_json(path)


def collect_runs(results, cases, only=None):
    runs = []
    for arm in sorted(os.listdir(results)):
        ad = os.path.join(results, arm)
        if not os.path.isdir(ad) or arm.startswith('.'):
            continue
        for name in sorted(os.listdir(ad)):
            d = os.path.join(ad, name)
            mp = os.path.join(d, 'meta.json')
            if not os.path.exists(mp):
                continue
            m = read_json(mp)
            rid = '%s/%s' % (arm, name)
            if m.get('dry_run') or m.get('error') or m.get('case') not in cases:
                continue
            if only and rid not in only:
                continue
            runs.append({'id': rid, 'arm': arm, 'case': m['case'], 'repeat': m.get('repeat'), 'run_dir': d,
                         'agent_cost_usd': m.get('cost_usd'), 'seconds': m.get('seconds'), 'agent_model': m.get('model')})
    return runs


def summarize(rows):
    lines = []
    arms = sorted({r['arm'] for r in rows})
    hdr = ('%-18s %5s %13s %13s %13s | %4s %5s %6s %5s | %6s %8s %5s' %
           ('arm', 'fault', 'Cause-pass', 'strict', 'lenient', 'hlth', 'clean', 'benign', 'false', 'calls', 'usage$', 'err'))
    lines += [hdr, '-' * len(hdr)]
    tot = {'calls': 0, 'cost': 0.0}
    for arm in arms + ['ALL']:
        rs = [r for r in rows if arm == 'ALL' or r['arm'] == arm]
        fr = [r for r in rs if r['outcome'].get('kind') in ('fault', 'multi')]
        hr = [r for r in rs if r['outcome'].get('kind') == 'healthy']
        c = sum(bool(r['outcome'].get('cause')) for r in fr)
        cs = sum(bool(r['outcome'].get('cause_strict')) for r in fr)
        cl = sum(bool(r['outcome'].get('cause_lenient')) for r in fr)
        h = {o: sum(r['outcome'].get('outcome') == o for r in hr) for o in HEALTHY_OUTCOMES}
        calls = sum(r['usage']['calls'] for r in rs)
        cost = sum(r['usage']['cost_usd'] for r in rs)
        err = sum(bool(r.get('error')) for r in rs)
        pct = lambda a, b: '%3d/%-3d %3.0f%%' % (a, b, 100.0 * a / b) if b else '-'
        lines.append('%-18s %5d %13s %13s %13s | %4d %5d %6d %5d | %6d %8.2f %5d' % (
            arm, len(fr), pct(c, len(fr)), pct(cs, len(fr)), pct(cl, len(fr)), len(hr), h['clean'], h['benign-defect-noted'],
            h['false-alarm'], calls, cost, err))
        if arm == 'ALL':
            tot.update(calls=calls, cost=cost)
    lines.append('')
    lines.append('Cause-pass: launch (tier 3 only), component, stage and mechanism (majority of votes "accepted") all pass;')
    lines.append('strict: every vote accepted; lenient: any vote accepted.  hlth: healthy-case runs, by 3-way outcome.')
    lines.append('calls / usage$: scorer model calls and their total_cost_usd (cached calls counted at their first cost).')
    return '\n'.join(lines), tot


def fact_table(rows):
    """Per arm, how often each fact passes on fault cases (single-fault keys only)."""
    lines = ['%-18s %5s %7s %9s %6s %9s %9s %6s %6s %9s %6s' % ('arm', 'fault', 'launch*', 'component', 'stage', 'mech-acc',
                                                                'near-miss', 'other', 'split', 'located**', 'asks')]
    for arm in sorted({r['arm'] for r in rows}) + ['ALL']:
        ar = [r for r in rows if (arm == 'ALL' or r['arm'] == arm) and r.get('facts')]
        fr = [r for r in ar if r['outcome'].get('kind') == 'fault']
        lk = [r for r in fr if r['facts'].get('launch') is not None]
        lo = [r for r in ar if r['facts'].get('located') is not None]
        mv = [r['mechanism'].get('verdict') for r in fr]
        lines.append('%-18s %5d %7s %9d %6d %9d %9d %6d %6d %9s %6d' % (
            arm, len(fr), '%d/%d' % (sum(bool(r['facts']['launch']) for r in lk), len(lk)),
            sum(bool(r['facts'].get('component')) for r in fr), sum(bool(r['facts'].get('stage')) for r in fr),
            mv.count('accepted'), mv.count('near-miss'), mv.count('other') + mv.count('none'), mv.count('split'),
            '%d/%d' % (sum(bool(r['facts']['located']) for r in lo), len(lo)), sum(bool(r.get('asks_operator')) for r in ar)))
    lines.append('Single-fault cases only (day-count is in the table above).  * launch is scored only on tier-3 cases (a pool')
    lines.append('of many launches): passed/scored.  ** located: the report names every keyed launch, all cases that have one.')
    lines.append('asks: reports with at least one question or check for the operator.')
    return '\n'.join(lines)


def traps(path, keys, caller, votes):
    """The scorer on hand-labelled trap reports (tests/judge_set.json): correct -> pass or clean,
    partial/wrong/unknown -> fail, false-alarm -> false-alarm."""
    items = read_json(path)
    want = {'correct': True, 'partial': False, 'wrong': False, 'unknown': False}
    ok = 0
    for it in items:
        key = keys['cases'][it['case']]
        r = score_report(key, keys, it['report'], caller, votes)
        o = r['outcome']
        if key['kind'] == 'healthy':
            got = o.get('outcome')
            hit = (got == 'false-alarm') == (it['expect'] == 'false-alarm')
        else:
            got = o.get('cause')
            hit = got == want.get(it['expect'])
        ok += hit
        print('%-4s %-28s expect %-11s scorer %s' % ('ok' if hit else 'MISS', it['id'], it['expect'], got))
    print('\nscorer agrees with the hand labels on %d of %d' % (ok, len(items)))
    return ok, len(items)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--keys', default=os.path.join(HERE, 'keys_v3.json'))
    ap.add_argument('--results')
    ap.add_argument('--report', help='score one report file (with --case)')
    ap.add_argument('--case')
    ap.add_argument('--traps', help='a JSON list of {id, case, report, expect} (tests/judge_set.json)')
    ap.add_argument('--out', help='write the scored rows here (JSON)')
    ap.add_argument('--summary', help='write the per-arm summary table here')
    ap.add_argument('--model', default='sonnet')
    ap.add_argument('--votes', type=int, default=3)
    ap.add_argument('--jobs', type=int, default=2, help='model calls at once (default %(default)d)')
    ap.add_argument('--cache', help='cache folder (default: RESULTS_DIR/.score-cache)')
    ap.add_argument('--only', action='append', help='score only this run id (<arm>/<run>); repeatable')
    ap.add_argument('--only-file', help='a JSON list of run ids to score')
    ap.add_argument('--limit', type=int, help='score at most N runs')
    ap.add_argument('--quiet-ids', help='a JSON list of run ids whose results are written to --out but never printed')
    ap.add_argument('--extract-cmd', help='replace the extraction command (tests)')
    ap.add_argument('--judge-cmd', help='replace the mechanism-judge command (tests)')
    a = ap.parse_args(argv)
    keys = load_keys(a.keys)
    cache = a.cache or (os.path.join(a.results, '.score-cache') if a.results else None)
    xc = Caller(a.model, a.extract_cmd.split() if a.extract_cmd else None, cache, a.jobs)
    jc = Caller(a.model, a.judge_cmd.split() if a.judge_cmd else None, cache, a.jobs)
    jc.sem = xc.sem                                   # one limit for both kinds of call

    class Both:                                       # extraction and judging may use different commands
        def call(self, prompt, kind, tag='', name=None):
            return (xc if kind == 'extract' else jc).call(prompt, kind, tag, name)

    caller = Both()
    if a.traps:
        ok, n = traps(a.traps, keys, caller, a.votes)
        return 0 if ok == n else 1
    if a.report:
        r = score_report(keys['cases'][a.case], keys, read_text(a.report), caller, a.votes)
        r['usage'] = usage(r)
        json.dump(r, sys.stdout, indent=1)
        print()
        return 0
    only = set(a.only or [])
    if a.only_file:
        only |= set(read_json(a.only_file))
    quiet = set(read_json(a.quiet_ids)) if a.quiet_ids else set()
    runs = collect_runs(a.results, keys['cases'], only or None)
    if a.limit:
        runs = runs[:a.limit]
    done = {}
    if a.out and os.path.exists(a.out):               # keep rows scored before (the cache makes them free anyway)
        try:
            done = {r['id']: r for r in read_json(a.out).get('rows', [])}
        except ValueError:
            done = {}

    def one(run):
        text = read_text(os.path.join(run['run_dir'], 'final.md'))
        key = keys['cases'][run['case']]
        r = score_report(key, keys, text, caller, a.votes)
        r.update({k: run[k] for k in ('id', 'arm', 'case', 'repeat', 'run_dir', 'agent_cost_usd', 'seconds', 'agent_model')})
        r['kind'] = key['kind']
        r['usage'] = usage(r)
        return r

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for r in ex.map(one, runs):
            rows.append(r)
            done[r['id']] = r
            if r['id'] not in quiet:
                o = r['outcome']
                print('%-30s %-22s %-8s %-20s $%.4f%s' % (r['id'], r['case'], r['kind'],
                                                          o.get('outcome') or ('PASS' if o.get('cause') else 'fail'),
                                                          r['usage']['cost_usd'], '  ERROR ' + r['error'] if r.get('error') else ''))
            else:
                print('%-30s (held out: written to the output only)' % r['id'])
            sys.stdout.flush()
            if a.out:
                write_json(a.out, {'rows': sorted(done.values(), key=lambda x: x['id'])})
    allrows = sorted(done.values(), key=lambda x: x['id'])
    table, tot = summarize(allrows)
    meta = {'scored': len(allrows), 'model_flag': a.model, 'votes': a.votes, 'keys': os.path.abspath(a.keys),
            'keys_sha256': sha(read_text(a.keys)), 'extract_prompt_sha256': sha(EXTRACT_PROMPT),
            'judge_prompt_sha256': sha(JUDGE_PROMPT), 'scorer_calls': tot['calls'], 'scorer_cost_usd': round(tot['cost'], 4),
            'fresh_calls_this_run': xc.fresh_calls + jc.fresh_calls,
            'fresh_cost_usd_this_run': round(xc.fresh_cost + jc.fresh_cost, 4),
            'models': sorted({m for r in allrows for m in r['usage']['models']})}
    if a.out:
        write_json(a.out, {'meta': meta, 'rows': allrows})
    text = table + '\n\n' + fact_table(allrows) + '\n\n' + json.dumps(meta, indent=1) + '\n'
    if a.summary:
        write_text(a.summary, text)
    print()
    print(text)
    return 1 if any(r.get('error') for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
