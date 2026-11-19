#!/usr/bin/env python3
"""Write the RESULTS page of the v3 DAQ-skill eval: page content only (a <title>, <style> and the body), which the
claude.ai artifact publisher wraps in a document skeleton.  Opens as a local file too.

    python3 report_v3.py --pilot OUT [--pilot OUT2 ...] --m0 M0_DIR [--verdict VERDICT.json]
                         --predictions PREDICTIONS.json --commit SHA --out results.html
                         [--model default] [--cases-v3 F] [--cases-real F] [--keys F] [--title T] [--note TEXT ...]

Inputs.  Nothing on the page is typed by hand: every number is read from these files or computed from them.
  --pilot OUT     a pilot.py results folder (one batch; its id is the folder name): rows.json (verdict.py's schema),
                  scored.json (score.py), usage.json and the run folders OUT/<arm>/<run>/ (meta.json, final.md,
                  evidence.json).  Repeatable.
  --m0 DIR        the M0 Haiku control folder: scored.json (the keys as run) and scored-keyfix.json (the fixed key),
                  run folders DIR/<arm>/<run>/ (arms m0-none, m0-crib, m0-starved).
  --verdict F     verdict.py's output on the pilot rows.  verdict.py is also run here on the pilot rows (and is the
                  source when --verdict is not given); any difference is listed at the top of the page.
  --predictions   the pre-registered predictions file: its rules are quoted, its P1 and P1b outcomes are the
                  scorer's validation, its definitions name the arms and families.
  --model         the model flag (rows' 'model') of the verdict runs: 'default' for the pilot; smoke tests use haiku.

Sections, in order: header; headline findings; the verdict; per arm and family; the controls (P2, P3, P3m); every
case; cases an arm missed; usage.

Privacy.  Family C reports are about real MFX logs.  Text taken from a family C report passes safe_text(): a line is
dropped if it holds a home-directory path of anyone but mfxopr (/home/<x>/, /sdf|/cds/home/<x>/<user>/, /cds/home/opr/
<user>), an e-mail or user@host, a ~user, an identity word (user, owner, author, login, ...) followed by a name, or a
personal title or two capitalised words after by/from/thanks/cc; the quote is cut to 200 characters.  Operator
questions and answers, and the reports' asks, are never printed.  Person names in general cannot be detected; the
filter is a heuristic over short quotes.

Standard library only, Python 3.6+.
"""

import argparse
import html
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score   # noqa: E402  (KeyBook: the key of each case, as the scorer builds it)
import verdict as verdict_mod   # noqa: E402  (controls(): P2 on the M0 folder, with verdict.py's margins)

E = html.escape
ARM_ORDER = ['none', 'skills', 'map', 'both', 'pointer', 'crib', 'starved']
FAMILY_ORDER = ['A', 'B', 'C']
QUOTE_MAX = 300
QUOTE_MAX_C = 200
ALLOWED_USERS = frozenset(['mfxopr'])

# ---------------------------------------------------------------------------------------------------------------
# privacy filter (family C)

HOME_RE = re.compile(r'/home\d*/(?:opr/|[a-z]/)?([^/\s\'"`<>()\[\]{},;|]+)')
AT_RE = re.compile(r'([A-Za-z0-9_.+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)')
TILDE_RE = re.compile(r'(?<![\w/~])~([A-Za-z][\w.-]*)')
IDENT_RE = re.compile(r'\b(?:user(?:name)?s?|uid|owner|author|login|logged in as|whoami|submitted by|signed by|'
                      r'contact|e-?mail)\b\s*[:=]?\s*[\'"]?([A-Za-z][\w.-]*)', re.I)
TITLE_RE = re.compile(r'\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]')
TWO_CAPS_RE = re.compile(r'\b(?:by|from|thanks|thank you|cc|per|ask|asked|told)\s+[A-Z][a-z]+\s+[A-Z][a-z]+', re.I)
TWO_CAPS_STRICT = re.compile(r'[A-Z][a-z]+\s+[A-Z][a-z]+$')


def private_line(line):
    """True if a line of a family C report must not be printed (see the module docstring)."""
    for m in HOME_RE.finditer(line):
        if m.group(1).rstrip('.:') not in ALLOWED_USERS:
            return True
    for rx in (AT_RE, TILDE_RE):
        for m in rx.finditer(line):
            if m.group(1).rstrip('.') not in ALLOWED_USERS:
                return True
    for m in IDENT_RE.finditer(line):
        if m.group(1).rstrip('.') not in ALLOWED_USERS:
            return True
    if TITLE_RE.search(line):
        return True
    for m in TWO_CAPS_RE.finditer(line):
        if TWO_CAPS_STRICT.search(m.group(0)):       # the two words after the cue are both capitalised
            return True
    return False


def clip(text, limit):
    """Collapse white space and cut to at most limit characters, at a word boundary, with '...'."""
    t = ' '.join(text.split())
    if len(t) <= limit:
        return t
    cut = t[:limit - 3]
    if ' ' in cut[limit // 2:]:
        cut = cut[:cut.rfind(' ')]
    return cut.rstrip(' ,;:.') + '...'


def safe_text(text, limit=QUOTE_MAX_C):
    """Family C text for the page: private lines dropped, then cut to limit characters."""
    return clip('\n'.join(l for l in (text or '').splitlines() if not private_line(l)), limit)


def strip_md(line):
    line = re.sub(r'^\s*(?:#{1,6}\s*|[-*+]\s+|\d+[.)]\s+|>\s*)', '', line)
    return line.replace('**', '').replace('__', '').replace('`', '')


def conclusion_quote(report, family):
    """The opening of a report (its conclusion, as the agents write them), at most QUOTE_MAX characters (family C:
    QUOTE_MAX_C, private lines dropped first).  Tables and rules are skipped."""
    lines = (report or '').splitlines()
    if family == 'C':
        lines = [l for l in lines if not private_line(l)]
    out, n = [], 0
    for para in '\n'.join(lines).split('\n\n'):
        body = [strip_md(l) for l in para.splitlines() if l.strip() and not l.lstrip().startswith(('|', '```', '---'))]
        t = ' '.join(' '.join(body).split())
        if not t:
            continue
        out.append(t)
        n += len(t)
        if n >= QUOTE_MAX:
            break
    return clip(' '.join(out), QUOTE_MAX_C if family == 'C' else QUOTE_MAX)


def run_text(run, text, limit=QUOTE_MAX):
    """Any text a report produced (a component it named, a stage, a blamed process): family C through safe_text."""
    if text is None:
        return ''
    text = str(text)
    return safe_text(text, min(limit, QUOTE_MAX_C)) if run.get('family') == 'C' else clip(text, limit)


# ---------------------------------------------------------------------------------------------------------------
# loading

def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_opt(path, default=None):
    try:
        return read_json(path)
    except (OSError, ValueError):
        return default


def read_text(path):
    try:
        with open(path, errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def arm_of(folder, control=None):
    """'B.none.default' -> none; 'm0-crib' -> crib; a control wins."""
    if control:
        return control
    if '.' in folder:
        return folder.split('.')[1]
    return folder.split('-', 1)[1] if folder.startswith('m0-') else folder


def run_folders(out):
    found = set()
    for arm in sorted(os.listdir(out)) if os.path.isdir(out) else []:
        ad = os.path.join(out, arm)
        if arm.startswith('.') or not os.path.isdir(ad):
            continue
        for name in os.listdir(ad):
            if os.path.exists(os.path.join(ad, name, 'meta.json')):
                found.add('%s/%s' % (arm, name))
    return found


def attach(run, root):
    d = os.path.join(root, run['run_id'])
    run['dir'] = d
    run['meta'] = read_opt(os.path.join(d, 'meta.json'), {}) or {}
    run['ev'] = read_opt(os.path.join(d, 'evidence.json'), {}) or {}
    return run


def load_pilot(out):
    out = os.path.abspath(out)
    b = {'id': os.path.basename(out.rstrip('/')), 'path': out, 'warnings': [], 'kind': 'pilot'}
    rows = read_json(os.path.join(out, 'rows.json'))
    doc = read_opt(os.path.join(out, 'scored.json'), {'rows': [], 'meta': {}})
    sc = dict((r['id'], r) for r in doc.get('rows', []))
    runs = []
    for row in rows:
        run = attach(dict(row), out)
        run['batch'] = b['id']
        run['s'] = sc.get(row['run_id']) or {}
        runs.append(run)
    extra = sorted(run_folders(out) - set(r['run_id'] for r in rows))
    if extra:
        b['warnings'].append('%s: %d run folder(s) are not in rows.json and are not on this page: %s'
                             % (b['id'], len(extra), ', '.join(extra)))
    b.update(runs=runs, scored_meta=doc.get('meta', {}), usage=read_opt(os.path.join(out, 'usage.json'), {}) or {})
    return b


def m0_runs(doc, root, batch):
    runs = []
    for s in doc.get('rows', []):
        o = s.get('outcome') or {}
        h = (o.get('kind') or s.get('kind')) == 'healthy'
        run = {'run_id': s['id'], 'family': s.get('family') or 'A', 'case': s['case'],
               'arm': arm_of(s['arm'], s.get('control')), 'mode': s.get('mode') or 'm0',
               'model': s.get('model_flag') or 'default', 'repeat': s.get('repeat'), 'healthy': h,
               'cause_pass': None if h else bool(o.get('cause')), 'healthy_outcome': o.get('outcome') if h else None,
               'located': s.get('located'), 'calls': None, 'calls_no_guidance': None,
               'cost_usd': s.get('agent_cost_usd'), 'seconds': s.get('seconds'), 'error': s.get('error'),
               'scorer_usd': (s.get('usage') or {}).get('cost_usd'), 'batch': batch, 's': s}
        runs.append(attach(run, root))
    return runs


def load_m0(path, orig='scored.json', fixed='scored-keyfix.json'):
    path = os.path.abspath(path)
    bid = os.path.basename(path.rstrip('/'))
    d0 = read_json(os.path.join(path, orig))
    d1 = read_opt(os.path.join(path, fixed))
    b = {'id': bid, 'path': path, 'kind': 'm0', 'warnings': [], 'orig': m0_runs(d0, path, bid),
         'orig_meta': d0.get('meta', {}), 'fixed_name': fixed if d1 else None}
    b['fixed'] = m0_runs(d1, path, bid) if d1 else None
    b['fixed_meta'] = (d1 or {}).get('meta', {})
    b['runs'] = b['fixed'] if d1 else b['orig']
    if not d1:
        b['warnings'].append('%s: no %s; P2 shows the original scoring only' % (bid, fixed))
    return b


VERDICT_ROW_KEYS = ('run_id', 'family', 'case', 'arm', 'mode', 'model', 'repeat', 'healthy', 'cause_pass',
                    'healthy_outcome', 'located', 'calls', 'calls_no_guidance', 'cost_usd', 'seconds')


def run_verdict(runs, model):
    """verdict.py on these runs' rows (its own rules and margins), as a dict."""
    rows = [dict((k, r.get(k)) for k in VERDICT_ROW_KEYS) for r in runs]
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(rows, f)
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, 'verdict.py'), f.name, model], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode:
            raise SystemExit('verdict.py failed: %s' % p.stderr.strip()[-400:])
        return json.loads(p.stdout)
    finally:
        os.unlink(f.name)


def canon(x):
    """JSON-comparable form: NaN equal to NaN, floats to 9 digits, tuples as lists."""
    if isinstance(x, float):
        return 'NaN' if math.isnan(x) else round(x, 9)
    if isinstance(x, dict):
        return dict((k, canon(v)) for k, v in x.items())
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    return x


def verdict_diffs(given, computed):
    out = []
    for k in sorted(set(given) | set(computed)):
        if k not in given:
            out.append('the given verdict file has no %s (verdict.py now writes it)' % k)
        elif k not in computed:
            out.append('the given verdict file has %s, which verdict.py does not write' % k)
        elif canon(given[k]) != canon(computed[k]):
            out.append('%s differs between the given verdict file and verdict.py run on these rows' % k)
    return out


# ---------------------------------------------------------------------------------------------------------------
# small helpers

def score_of(r):
    if r.get('healthy'):
        return None if r.get('healthy_outcome') is None else r['healthy_outcome'] != 'false-alarm'
    return r.get('cause_pass')


def mark(r):
    """(css class, label) of one run: pass / part / fail / na."""
    if r.get('error') or score_of(r) is None:
        return 'na', 'error' if r.get('error') else 'not scored'
    if r.get('healthy'):
        ho = r['healthy_outcome']
        lab = {'clean': 'clean', 'benign-defect-noted': 'benign', 'false-alarm': 'false alarm'}.get(ho, ho)
        if ho == 'false-alarm':
            return 'fail', lab
        return ('pass', lab) if r.get('located') else ('part', lab + ', not located')
    if r.get('cause_pass'):
        return 'pass', 'cause'
    return ('part', 'located') if r.get('located') else ('fail', 'missed')


def pct(k, n):
    return 100.0 * k / n if n else float('nan')


def frac(k, n):
    if not n:
        return '0/0'
    return '%d/%d (%.1f%%)' % (k, n, pct(k, n))


def kn(v):
    """A verdict.py [k, n(, pct)] list as 'k/n (p%)'."""
    if not v:
        return 'n/a'
    return frac(v[0], v[1])


def num(x, f='%.1f'):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 'n/a'
    return f % x


def usd(x, f='$%.2f'):
    return num(x, f)


def pval(p):
    return 'n/a' if p is None else ('%.3g' % p)


def yes(b):
    return 'yes' if b else 'no'


def pf(b):
    return '<span class="m %s">%s</span>' % ('pass' if b else 'fail', 'PASS' if b else 'FAIL')


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def median(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def arm_key(a):
    return (ARM_ORDER.index(a) if a in ARM_ORDER else len(ARM_ORDER), a)


def pred(preds, pid):
    for p in preds.get('predictions', []):
        if p.get('id') == pid or p.get('id', '').startswith(pid + '-'):
            return p
    return {}


def first_sentence(text):
    text = text or ''
    m = re.search(r'\.\s', text)
    return text[:m.start() + 1] if m else text


def rid(r, batches_n):
    """The run id as the run folders name it (with its batch when several batches are shown)."""
    return r['run_id'] if batches_n < 2 else '%s:%s' % (r['batch'], r['run_id'])


def label_family(preds, f):
    """'B' -> 'sim-tree' (the predictions file's family names, 'B sim-tree', ...)."""
    fam = (preds.get('definitions') or {}).get('families') or {}
    for k in fam:
        if k.split()[0] == f:
            return k.split(None, 1)[1] if ' ' in k else k
    return f


# ---------------------------------------------------------------------------------------------------------------
# page parts

CSS = """
:root{--bg:#f5f6f8;--surface:#ffffff;--surface-2:#eef1f5;--code-bg:#f0f2f6;--ink:#17202c;--ink-2:#445063;--ink-3:#6a7586;
--rule:#d8dde5;--rule-strong:#b6bfcc;--accent:#1d5296;--accent-soft:#e2ebf7;--pass:#17723f;--pass-bg:#e0f1e6;
--part:#8f4c08;--part-bg:#f7eadb;--fail:#ab2a20;--fail-bg:#f8e4e1;--na:#4c586b;--na-bg:#e6e9ef;--warn-bg:#fbf3d6;
--warn-ink:#5e4a07;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1318;--surface:#161b22;--surface-2:#1c232c;
--code-bg:#12171e;--ink:#e4e8ee;--ink-2:#b0bac9;--ink-3:#8691a2;--rule:#29313c;--rule-strong:#3b4553;--accent:#8db8f2;
--accent-soft:#1a2b43;--pass:#6fd49a;--pass-bg:#11301e;--part:#f0ac68;--part-bg:#35250f;--fail:#ff9188;--fail-bg:#3a1714;
--na:#b4bfd4;--na-bg:#28303d;--warn-bg:#2d2914;--warn-ink:#efd98a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1318;--surface:#161b22;--surface-2:#1c232c;--code-bg:#12171e;--ink:#e4e8ee;--ink-2:#b0bac9;
--ink-3:#8691a2;--rule:#29313c;--rule-strong:#3b4553;--accent:#8db8f2;--accent-soft:#1a2b43;--pass:#6fd49a;--pass-bg:#11301e;
--part:#f0ac68;--part-bg:#35250f;--fail:#ff9188;--fail-bg:#3a1714;--na:#b4bfd4;--na-bg:#28303d;--warn-bg:#2d2914;
--warn-ink:#efd98a;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
font-size:15px;line-height:1.55;-webkit-text-size-adjust:100%}
.page{max-width:1160px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:36px 80px}
h1,h2,h3{font-family:"Space Grotesk","Inter",system-ui,-apple-system,"Segoe UI",sans-serif;text-wrap:balance;color:var(--ink)}
h1{font-size:clamp(1.9rem,1.5rem + 1.8vw,2.6rem);line-height:1.08;letter-spacing:-.02em;margin:6px 0 14px;font-weight:700}
h2{font-size:clamp(1.3rem,1.1rem + .8vw,1.65rem);line-height:1.22;letter-spacing:-.01em;margin:0 0 12px;font-weight:600}
h3{font-size:1.08rem;line-height:1.3;margin:24px 0 8px;font-weight:600}
p,li{max-width:68ch}p{margin:0 0 12px}a{color:var(--accent);text-underline-offset:2px}
code,.mono{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
code{font-size:.86em;background:var(--surface-2);padding:1px 4px;border-radius:3px;overflow-wrap:anywhere}
.eyebrow{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;letter-spacing:.08em;
text-transform:uppercase;color:var(--accent);margin:0}
.meta{color:var(--ink-2);font-size:14px;max-width:none}
.muted{color:var(--ink-3);font-size:13.5px}
nav.toc ul{list-style:none;margin:18px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:4px 18px;font-size:14px}
nav.toc a{color:var(--ink-2);text-decoration:none}nav.toc a:hover{color:var(--accent);text-decoration:underline}
section{border-top:1px solid var(--rule-strong);padding-top:24px;margin-top:32px;min-width:0}
ul.findings{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:7px}
.verdict-line{font-family:"Space Grotesk","Inter",system-ui,sans-serif;font-size:1.35rem;font-weight:600;margin:0 0 6px}
.rule{border-left:3px solid var(--rule-strong);padding:6px 0 6px 12px;margin:8px 0 14px;color:var(--ink-2);font-size:14px;max-width:80ch}
.rule b{color:var(--ink)}
.warn{background:var(--warn-bg);color:var(--warn-ink);border-radius:4px;padding:10px 14px;margin:14px 0 0;font-size:14px}
.warn ul{margin:4px 0 0;padding-left:18px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;min-width:0;margin:6px 0 10px}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
td.n,th.n{text-align:right}td.n{white-space:nowrap}th{min-width:4.5em}
tr.grp td{background:var(--surface-2);font-weight:600;font-size:12.5px;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3)}
.m{display:inline-block;font-size:12px;font-weight:600;border-radius:3px;padding:1px 7px;margin:1px 3px 1px 0;white-space:nowrap}
.m.pass{background:var(--pass-bg);color:var(--pass)}.m.part{background:var(--part-bg);color:var(--part)}
.m.fail{background:var(--fail-bg);color:var(--fail)}.m.na{background:var(--na-bg);color:var(--na)}
.ids{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--ink-2);
overflow-wrap:anywhere;line-height:1.7;min-width:18rem}
td code{white-space:nowrap;overflow-wrap:normal}
.ids .pass{color:var(--pass)}.ids .fail{color:var(--fail)}.ids .part{color:var(--part)}.ids .na{color:var(--na)}
.keytxt{color:var(--ink-2);font-size:13px;min-width:16rem;max-width:34rem}
.case{background:var(--surface);border:1px solid var(--rule);border-radius:5px;padding:12px 14px;margin:14px 0;min-width:0}
.case-head{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
.key{background:var(--surface-2);border-radius:4px;padding:7px 10px;font-size:13.5px;margin:8px 0;color:var(--ink-2)}
.miss{border-top:1px solid var(--rule);padding:10px 0 4px;min-width:0}
.miss-head{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline;font-size:14px}
.facts{margin:6px 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;color:var(--ink-2)}
.facts .ok{color:var(--pass)}.facts .no{color:var(--fail)}
.quote{border-left:3px solid var(--rule-strong);padding-left:10px;color:var(--ink-2);font-size:13.5px;overflow-wrap:anywhere;margin:6px 0 4px;max-width:80ch}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:18px;align-items:start}
.grid2>div{min-width:0}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:6px 0 10px;font-size:14px}
dl.kv dt{color:var(--ink-3)}dl.kv dd{margin:0;min-width:0;overflow-wrap:anywhere}
@media (max-width:440px){dl.kv{grid-template-columns:1fr}dl.kv dd{margin-bottom:6px}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&'
         'family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap">\n')

SECTIONS = [('findings', 'Headline findings'), ('verdict', 'The verdict'), ('arms', 'Per arm and family'),
            ('controls', 'The controls'), ('cases', 'Every case'), ('missed', 'Cases an arm missed'), ('usage', 'Usage')]


def section(sid, title, body):
    return '<section id="%s"><h2>%s</h2>%s</section>' % (sid, E(title), body)


def rule_block(preds, pid, label=None):
    p = pred(preds, pid)
    if not p.get('rule'):
        return ''
    return '<div class="rule"><b>%s, pre-registered:</b> %s</div>' % (E(label or p.get('id', pid)), E(p['rule']))


def chip(r, text=None):
    cls, lab = mark(r)
    return '<span class="m %s" title="%s">%s</span>' % (cls, E(r['run_id']), E(text or lab))


def table(head, rows, num_cols=()):
    h = ''.join('<th%s>%s</th>' % (' class="n"' if i in num_cols else '', E(c)) for i, c in enumerate(head))
    body = []
    for row in rows:
        if isinstance(row, str):
            body.append(row)
            continue
        body.append('<tr>%s</tr>' % ''.join('<td%s>%s</td>' % (' class="n"' if i in num_cols else '', c)
                                           for i, c in enumerate(row)))
    return '<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (h, ''.join(body))


# --- header

def header(d):
    runs, batches = d['all_runs'], d['batches']
    models = {}
    for r in runs:
        m = r['meta'].get('model') or (r.get('s') or {}).get('agent_model')
        models.setdefault(r.get('model'), set())
        if m:
            models[r.get('model')].add(m)
    mtxt = '; '.join('%s = %s' % (k, ', '.join(sorted(v)) or 'model not recorded') for k, v in sorted(models.items()))
    started = sorted(r['meta']['started'] for r in runs if r['meta'].get('started'))
    when = ('runs from %s to %s (UTC)' % (started[0].replace('T', ' '), started[-1].replace('T', ' '))) if started else 'run times not recorded'
    blist = ', '.join('<code>%s</code> (%d runs)' % (E(b['id']), len(b['runs'])) for b in batches)
    sm = d['scorer_meta']
    p1, p1b = pred(d['preds'], 'P1-scorer-agreement'), pred(d['preds'], 'P1b-scorer-power')
    parts = ['<header><p class="eyebrow">DAQ skill eval v3 &middot; results</p><h1>%s</h1>' % E(d['title'])]
    parts.append('<p class="meta">Commit <code>%s</code> &middot; %s &middot; agent models: %s &middot; %d runs &middot; batches: %s</p>'
                 % (E(d['commit']), E(when), E(mtxt), len(runs), blist))
    parts.append('<p class="meta">Scorer: %s (flag <code>%s</code>), %s judge votes, keys sha256 <code>%s</code>. '
                 'Validation: P1 %s P1b %s</p>' % (
                     E(', '.join(sm.get('models') or ['not recorded'])), E(str(sm.get('model_flag'))), E(str(sm.get('votes'))),
                     E((sm.get('keys_sha256') or '')[:12]), E(first_sentence(p1.get('outcome')) or 'no outcome recorded.'),
                     E(first_sentence(p1b.get('outcome')) or 'no outcome recorded.')))
    caveats = [x for x in (p1.get('outcome'), p1b.get('outcome')) if x and x != first_sentence(x)]
    if caveats:
        parts.append('<p class="muted">As recorded in the predictions file: P1 %s P1b %s</p>' % (
            E(p1.get('outcome') or ''), E(p1b.get('outcome') or '')))
    for n in d['notes']:
        parts.append('<p class="meta">%s</p>' % E(n))
    if d['warnings']:
        parts.append('<div class="warn"><b>Checks that need a look before this page is shared:</b><ul>%s</ul></div>'
                     % ''.join('<li>%s</li>' % E(w) for w in d['warnings']))
    parts.append('<nav class="toc"><ul>%s</ul></nav></header>' % ''.join('<li><a href="#%s">%s</a></li>' % (s, E(t)) for s, t in SECTIONS))
    return ''.join(parts)


# --- findings

def m1_runs(d, family):
    return [r for r in d['pilot_runs'] if r['family'] == family and r.get('mode') == 'm1' and r.get('model') == d['model']]


def findings(d):
    v, out = d['verdict'], []
    ov = v.get('P6_overall') or ['n/a', '']
    out.append('The pre-registered verdict on "knowing where things are matters more than procedure" is <b>%s</b>: %s.'
               % (E(str(ov[0])), E(str(ov[1]))))
    for fam, key in (('B', 'P4_B'), ('C', 'P5_C')):
        fv = v.get(key) or {}
        runs = m1_runs(d, fam)
        if not runs:
            continue
        loc = fv.get('located') or {}
        calls = fv.get('calls') or {}
        if fv.get('pairs'):
            out.append('Family %s: with the pointer the agent reached the keyed launch in %s calls on average, with no '
                       'guidance in %s (G = %s calls over %d pair(s), one-sided Wilcoxon p = %s); it located the launch in %s '
                       'runs with the pointer and %s with none.' % (
                           fam, num(calls.get('pointer')), num(calls.get('none')), num(fv.get('G_calls'), '%.2f'), fv['pairs'],
                           pval(fv.get('G_calls_p')), kn(loc.get('pointer')), kn(loc.get('none'))))
        else:
            out.append('Family %s: no (case, repeat) pair has both a none and a pointer run on model %s, so G is not measured.'
                       % (fam, E(d['model'])))
        arms = [a for a in ('none', 'skills', 'map', 'both') if (loc.get(a) or [0, 0])[1]]
        if arms:
            out.append('Family %s, located by arm: %s. Mean calls to evidence: %s.' % (
                fam, '; '.join('%s %s' % (a, kn(loc[a])) for a in arms),
                '; '.join('%s %s' % (a, num(calls.get(a))) for a in arms)))
    p3m = v.get('P3m_controls_M1_pooled')
    if p3m and (p3m.get('none_pooled') or [0, 0])[1]:
        out.append('P3m controls (families %s pooled): pointer %s against none %s, positive control %s (needs +%s points); B starved '
                   '%s against none %s on the same pools, negative control %s (needs -%s).' % (
                       '+'.join(p3m.get('families', [])), kn(p3m.get('pointer_pooled')), kn(p3m.get('none_pooled')),
                       'passes' if p3m.get('positive_pass') else 'fails', num(p3m.get('positive_margin_needed'), '%g'),
                       kn(p3m.get('starved')), kn(p3m.get('none_on_starved_pools')),
                       'passes' if p3m.get('negative_pass') else 'fails', num(p3m.get('negative_margin_needed'), '%g')))
    for tag, c in d['p2']:
        out.append('P2 controls (M0 Haiku, %s): crib %s against none %s, positive control %s; starved %s against none %s on '
                   'the same pools, negative control %s.' % (
                       tag, kn(c['crib']), kn(c['none']), 'passes' if c['positive_pass'] else 'fails', kn(c['starved']),
                       kn(c['none_on_starved_pools']), 'passes' if c['negative_pass'] else 'fails'))
    hl = [r for r in d['pilot_runs'] if r.get('healthy') and r.get('healthy_outcome')]
    if hl:
        fa = [r for r in hl if r['healthy_outcome'] == 'false-alarm']
        by = {}
        for r in fa:
            by[(r['family'], r['arm'])] = by.get((r['family'], r['arm']), 0) + 1
        out.append('Healthy cases: %d of %d runs raised a false alarm%s.' % (
            len(fa), len(hl), (' (' + ', '.join('%s %s: %d' % (f, a, n) for (f, a), n in sorted(by.items())) + ')') if by else ''))
    m1 = [r for r in d['pilot_runs'] if r.get('mode') == 'm1']
    q = [r['meta'].get('operator_questions') for r in m1 if r['meta'].get('operator_questions') is not None]
    if q:
        out.append('Ask-operator: %d of %d cold-start runs asked the operator at least once (%d questions in all).'
                   % (sum(1 for x in q if x), len(q), sum(q)))
    pr = d['pilot_runs']
    if pr:
        ag = sum(r.get('cost_usd') or 0 for r in pr)
        by = {}
        for r in pr:
            by.setdefault((r['family'], r['arm'], r['model']), []).append(r.get('cost_usd'))
        out.append('Agent usage over the %d pilot runs: %s; mean per run %s.' % (
            len(pr), usd(ag), '; '.join('%s %s%s %s' % (f, a, '' if m == d['model'] else ' (' + m + ')', usd(mean(v)))
                                        for (f, a, m), v in sorted(by.items(), key=lambda x: (x[0][0], arm_key(x[0][1]), x[0][2])))))
    return '<ul class="findings">%s</ul><p class="muted">Each sentence is filled from the input files; edit the wording, not the numbers.</p>' % ''.join('<li>%s</li>' % x for x in out)


# --- verdict

def family_block(d, fam, fv, sens):
    loc, calls = fv.get('located') or {}, fv.get('calls') or {}
    rows = []
    for a in ('none', 'skills', 'map', 'both', 'pointer'):
        if (loc.get(a) or [0, 0])[1] or calls.get(a) is not None:
            share = (fv.get('shares') or {}).get(a)
            rows.append(['<b>%s</b>' % E(a), kn(loc.get(a)), num(calls.get(a)),
                         num(((sens or {}).get('calls') or {}).get(a)),
                         num(share, '%.2f') if share is not None else ('' if a in ('none', 'pointer') else 'n/a')])
    kv = [('Pairs (case, repeat) with none and pointer', str(fv.get('pairs', 0))),
          ('G on calls (none minus pointer, mean)', '%s calls; one-sided Wilcoxon p = %s over %s non-zero pair(s); real: %s'
           % (num(fv.get('G_calls'), '%.2f'), pval(fv.get('G_calls_p')), fv.get('G_calls_nonzero_pairs', 'n/a'), yes(fv.get('G_calls_real')))),
          ('G on Located (pointer minus none)', '%s points of runs; real: %s' % (num(100 * fv['G_loc'] if fv.get('G_loc') is not None else None),
                                                                              yes(fv.get('G_loc_real')))),
          ('Primary metric', E(str(fv.get('primary') or 'none (G not real)'))),
          ('Noise floor (none, repeat 1 vs 2)', num(fv.get('noise_floor'), '%.3g')),
          ('Verdict', '<b>%s</b> (%s)' % (E(str(fv.get('verdict'))), E(str(fv.get('why', '')))))]
    if sens:
        kv.append(('Sensitivity, guidance calls left out (descriptive)', 'G = %s calls, p = %s; shares on calls: %s' % (
            num(sens.get('G_calls'), '%.2f'), pval(sens.get('G_calls_p')),
            ', '.join('%s %s' % (k, num(x, '%.2f')) for k, x in sorted((sens.get('shares_on_calls') or {}).items())))))
    dl = '<dl class="kv">%s</dl>' % ''.join('<dt>%s</dt><dd>%s</dd>' % (E(k), v) for k, v in kv)
    t = table(['Arm', 'Located', 'Calls to evidence (mean)', 'Calls, no guidance (mean)', 'Share of G'], rows, (1, 2, 3, 4))
    return '<div><h3>Family %s: %s</h3>%s%s</div>' % (E(fam), E(label_family(d['preds'], fam)), dl, t)


def verdict_section(d):
    v = d['verdict']
    ov = v.get('P6_overall') or ['n/a', '']
    sens = v.get('sensitivity_calls_no_guidance') or {}
    body = ['<p class="verdict-line">Overall: %s</p><p class="meta">%s. Verdicts read on model flag <code>%s</code>%s.</p>' % (
        E(str(ov[0])), E(str(ov[1])), E(d['model']), '' if d['verdict_given'] else ', computed here by verdict.py')]
    body.append(rule_block(d['preds'], 'P6-verdict-rules', 'P6'))
    body.append('<div class="grid2">%s%s</div>' % (family_block(d, 'B', v.get('P4_B') or {}, sens.get('B')),
                                                     family_block(d, 'C', v.get('P5_C') or {}, sens.get('C'))))
    body.append(rule_block(d['preds'], 'P4-gap-B', 'P4'))
    body.append(rule_block(d['preds'], 'P5-gap-C', 'P5'))
    p7 = pred(d['preds'], 'P7-expected-verdict')
    if p7.get('expected'):
        body.append('<p class="muted">Expected before any run (P7, descriptive): %s</p>' % E(p7['expected']))
    return section('verdict', 'The verdict', ''.join(body))


# --- per arm

def arm_rows(runs, d):
    groups = {}
    for r in runs:
        groups.setdefault((r['family'], r['arm'], r.get('model')), []).append(r)
    out = []
    for (fam, arm, model) in sorted(groups, key=lambda k: (FAMILY_ORDER.index(k[0]) if k[0] in FAMILY_ORDER else 9, arm_key(k[1]), k[2] or '')):
        rs = groups[(fam, arm, model)]
        loc = [r['located'] for r in rs if r.get('located') is not None]
        calls = [r.get('calls') for r in rs]
        cng = [r.get('calls_no_guidance') for r in rs]
        cens = sum(1 for r in rs if r['ev'].get('censored'))
        has_ev = any(r['ev'] for r in rs)
        fault = [r for r in rs if not r.get('healthy') and r.get('cause_pass') is not None]
        hl = [r.get('healthy_outcome') for r in rs if r.get('healthy') and r.get('healthy_outcome')]
        oq = [r['meta'].get('operator_questions') for r in rs if r['meta'].get('operator_questions') is not None]
        out.append(['<b>%s</b>' % E(fam), '<b>%s</b>' % E(arm), E(model or ''), str(len(rs)),
                    frac(sum(1 for x in loc if x), len(loc)),
                    '%s / %s' % (num(mean(calls)), num(median(calls), '%g')),
                    '%s / %s' % (num(mean(cng)), num(median(cng), '%g')),
                    str(cens) if has_ev else 'n/a',
                    frac(sum(1 for r in fault if r['cause_pass']), len(fault)) if fault else '',
                    ('%d / %d / %d' % (hl.count('clean'), hl.count('benign-defect-noted'), hl.count('false-alarm'))) if hl else '',
                    ('%d / %d' % (sum(1 for x in oq if x), sum(oq))) if oq else 'n/a',
                    usd(mean([r.get('cost_usd') for r in rs]), '$%.3f'), num(mean([r.get('seconds') for r in rs])),
                    str(sum(1 for r in rs if r.get('error')))])
    return out


def arms_section(d):
    head = ['Family', 'Arm', 'Model', 'Runs', 'Located', 'Calls to evidence: mean / median',
            'Calls, no guidance: mean / median', 'Never reached evidence', 'Cause pass (fault cases)',
            'Healthy: clean / benign / false alarm', 'Asked operator: runs / questions', 'Mean usage', 'Mean seconds', 'Errors']
    cols = tuple(range(3, 14))
    body = [table(head, arm_rows(d['pilot_runs'], d), cols)]
    m0 = d['m0']
    if m0:
        body.append('<h3>Family A at M0 (the P2 control runs, %s)</h3>' % E('fixed key' if m0.get('fixed') else 'keys as run'))
        body.append(table(head, arm_rows(m0['runs'], d), cols))
    defs = (d['preds'].get('definitions') or {})
    arms = defs.get('arms') or {}
    sc = defs.get('scores') or {}
    items = ['<li><b>%s</b>: %s</li>' % (E(k), E(v)) for k, v in arms.items()]
    items += ['<li><b>%s</b>: %s</li>' % (E(k), E(sc[k])) for k in ('Located', 'Calls to evidence', 'Usage', 'Seconds') if k in sc]
    body.append('<p class="muted">Calls to evidence: the censored value (total + 1) counts for a run that never read the '
                'keyed launch; "never reached evidence" counts those runs. Asked the operator: runs with at least one '
                'ask-operator question, and all questions they asked. Calls, no guidance: Skill calls and reads of the installed guidance left out (descriptive). Definitions from the predictions file:</p><ul class="muted">%s</ul>'
                % ''.join(items))
    return section('arms', 'Per arm and family', ''.join(body))


# --- controls

def id_lists(runs, nb, fixed_from=None):
    """Run ids grouped by outcome; fixed_from: {run_id: original run} to flag a change by the key fix."""
    groups = [('pass', 'Passed'), ('fail', 'Failed'), ('na', 'Error or not scored')]
    out = []
    for cls, lab in groups:
        rs = [r for r in runs if (score_of(r) is True and cls == 'pass') or (score_of(r) is False and cls == 'fail')
              or ((r.get('error') or score_of(r) is None) and cls == 'na')]
        if cls != 'na':
            rs = [r for r in rs if not r.get('error')]
        if not rs:
            continue
        items = []
        for r in sorted(rs, key=lambda r: r['run_id']):
            flag = ''
            if fixed_from is not None:
                o = fixed_from.get(r['run_id'])
                if o is not None and score_of(o) != score_of(r):
                    flag = ' (changed by the key fix)'
            items.append('<span class="%s">%s</span>%s' % (cls, E(rid(r, nb)), E(flag)))
        out.append('<div><b>%s (%d):</b> %s</div>' % (lab, len(rs), ', '.join(items)))
    return '<div class="ids">%s</div>' % ''.join(out) if out else '<span class="muted">no runs</span>'


def pc(x):
    return 'n/a' if x is None or (isinstance(x, float) and math.isnan(x)) else '%.1f%%' % x


def margin_lines(c, pos):
    a = c.get(pos) or [0, 0, float('nan')]
    b = c.get('none') or c.get('none_pooled') or [0, 0, float('nan')]
    s = c.get('starved') or [0, 0, float('nan')]
    nb = c.get('none_on_starved_pools') or [0, 0, float('nan')]
    d1 = (a[2] - b[2]) if a[1] and b[1] else None
    d2 = (s[2] - nb[2]) if s[1] and nb[1] else None
    return ('<dl class="kv"><dt>Positive control</dt><dd>%s %s minus none %s = %s points (needs +%s) %s</dd>'
            '<dt>Negative control</dt><dd>starved %s minus none on the same pools %s = %s points (needs -%s) %s</dd>'
            '<dt>Shown able to detect a difference</dt><dd>%s</dd></dl>' % (
                E(pos), pc(a[2]), pc(b[2]), num(d1, '%+.1f'), num(c.get('positive_margin_needed'), '%g'),
                pf(c.get('positive_pass')), pc(s[2]), pc(nb[2]), num(d2, '%+.1f'),
                num(c.get('negative_margin_needed'), '%g'), pf(c.get('negative_pass')), yes(c.get('detects_difference'))))


def p2_block(d):
    m0 = d['m0']
    if not m0:
        return '<h3>P2: M0 Haiku controls</h3><p class="muted">No M0 control folder given.</p>'
    nb = 1
    orig, fixed = m0['orig'], m0.get('fixed')
    c0 = dict(d['p2'])
    body = ['<h3>P2: M0 Haiku controls, family A (batch <code>%s</code>)</h3>' % E(m0['id']), rule_block(d['preds'], 'P2-controls-M0-haiku', 'P2')]
    starved_cases = set(r['case'] for r in orig if r['arm'] == 'starved')
    rows = []
    origmap = dict((r['run_id'], r) for r in orig)
    for arm, label, pick in (('none', 'none', lambda r: r['arm'] == 'none'), ('crib', 'crib', lambda r: r['arm'] == 'crib'),
                             ('starved', 'starved', lambda r: r['arm'] == 'starved'),
                             ('none_on_starved_pools', 'none, on the starved pools', lambda r: r['arm'] == 'none' and r['case'] in starved_cases)):
        rs = [r for r in (fixed or orig) if pick(r)]
        rows.append(['<b>%s</b>' % E(label), kn(c0['keys as run'].get(arm)), kn(c0['fixed key'].get(arm)) if fixed else 'n/a',
                     id_lists(rs, nb, origmap if fixed else None) if arm != 'none_on_starved_pools' else '<span class="muted">the none runs of those cases, above</span>'])
    body.append(table(['Arm', 'Score, keys as run', 'Score, fixed key', 'Runs (marked by the fixed key)'], rows, (1, 2)))
    body.append('<p class="muted">Keys as run: <code>%s</code> (keys sha256 <code>%s</code>). Fixed key: <code>%s</code> (keys sha256 '
                '<code>%s</code>).</p>' % (E('scored.json'), E(m0['orig_meta'].get('keys_sha256', '')[:12]), E(m0.get('fixed_name') or 'none'),
                                           E((m0.get('fixed_meta') or {}).get('keys_sha256', '')[:12])))
    body.append('<div class="grid2"><div><p class="meta"><b>Keys as run</b></p>%s</div>%s</div>' % (
        margin_lines(c0['keys as run'], 'crib'),
        ('<div><p class="meta"><b>Fixed key</b></p>%s</div>' % margin_lines(c0['fixed key'], 'crib')) if fixed else ''))
    vp2 = (d['verdict'].get('P2_controls_M0_haiku') or {})
    if (vp2.get('none') or [0, 0])[1]:
        body.append('<p class="meta">The pilot rows also hold M0 Haiku runs: %s</p>' % margin_lines(vp2, 'crib'))
    out = pred(d['preds'], 'P2-controls-M0-haiku').get('outcome')
    if out:
        body.append('<p class="muted">Recorded in the predictions file: %s</p>' % E(out))
    return ''.join(body)


def p3_block(d):
    c = d['verdict'].get('P3_controls_M1_default')
    body = ['<h3>P3: M1 controls, family B, model <code>%s</code></h3>' % E(d['model']), rule_block(d['preds'], 'P3-controls-M1-default', 'P3')]
    if not c:
        return ''.join(body) + '<p class="muted">The verdict file has no P3.</p>'
    b = [r for r in m1_runs(d, 'B')]
    sc = set(r['case'] for r in b if r['arm'] == 'starved')
    rows = []
    for arm, label, rs in (('none', 'none', [r for r in b if r['arm'] == 'none']), ('pointer', 'pointer', [r for r in b if r['arm'] == 'pointer']),
                           ('starved', 'starved', [r for r in b if r['arm'] == 'starved']),
                           ('none_on_starved_pools', 'none, on the starved pools', [r for r in b if r['arm'] == 'none' and r['case'] in sc])):
        rows.append(['<b>%s</b>' % E(label), kn(c.get(arm)), id_lists(rs, d['nb'])])
    body.append(table(['Arm', 'Score', 'Runs'], rows, (1,)))
    body.append(margin_lines(c, 'pointer'))
    return ''.join(body)


def p3m_block(d):
    c = d['verdict'].get('P3m_controls_M1_pooled')
    body = ['<h3>P3m: M1 controls, families B and C pooled, model <code>%s</code></h3>' % E(d['model']),
            rule_block(d['preds'], 'P3m-controls-M1-pooled', 'P3m')]
    if not c:
        return ''.join(body) + '<p class="muted">The verdict file has no P3m (an older verdict.py).</p>'
    fams = c.get('families') or ['B', 'C']
    pooled = [r for f in fams for r in m1_runs(d, f)]
    nf = c.get('negative_family', 'B')
    neg = m1_runs(d, nf)
    sc = set(r['case'] for r in neg if r['arm'] == 'starved')
    pf_ = c.get('per_family') or {}
    rows = []
    for arm in ('none', 'pointer'):
        rows.append(['<b>%s, pooled</b>' % E(arm), kn(c.get(arm + '_pooled')),
                     '; '.join('%s %s' % (E(f), kn((pf_.get(f) or {}).get(arm))) for f in fams),
                     id_lists([r for r in pooled if r['arm'] == arm], d['nb'])])
    rows.append(['<b>%s starved</b>' % E(nf), kn(c.get('starved')), '', id_lists([r for r in neg if r['arm'] == 'starved'], d['nb'])])
    rows.append(['<b>%s none, on the starved pools</b>' % E(nf), kn(c.get('none_on_starved_pools')), '',
                 id_lists([r for r in neg if r['arm'] == 'none' and r['case'] in sc], d['nb'])])
    body.append(table(['Arm', 'Score', 'Per family', 'Runs'], rows, (1,)))
    cc = dict(c)
    cc['pointer'], cc['none'] = c.get('pointer_pooled'), c.get('none_pooled')
    body.append(margin_lines(cc, 'pointer'))
    return ''.join(body)


def controls_section(d):
    intro = ('<p>The controls show whether the instrument can see a difference before any arm is compared. A run scores '
             'when it passes Cause on a fault case, or does not raise a false alarm on a healthy case.</p>')
    return section('controls', 'The controls', intro + p2_block(d) + p3_block(d) + p3m_block(d))


# --- every case

def case_info(d, fam, case):
    """(question line, key line) for a case, from the case tables and the scorer's key."""
    book = d['book']
    if fam == 'C':
        c = book.real.get(case) or {}
        q = 'asked on %s about "%s"' % (c.get('today', '?'), c.get('phrase', '?'))
        k = book.key(case, 'm1') or {}
        stamp = (c.get('target') or '').rsplit('/', 1)[-1]
        if c.get('kind') == 'healthy':
            return q, 'healthy; launch %s' % stamp
        return q, '%s failed in %s (%s); launch %s' % ((k.get('component') or {}).get('name'), (k.get('stage') or {}).get('name'),
                                                     k.get('scripted_mechanism'), stamp)
    if fam == 'B':
        c = book.v3.get(case) or {}
        m1 = c.get('m1') or {}
        q = 'asked %s about "%s"' % (m1.get('now', '?'), m1.get('vague', '?'))
        k = book.key(case, 'm1') or {}
        stamp = m1.get('keyed_stamp', '?')
    else:
        k = book.key(case, 'm0') or {}
        q = clip(k.get('question') or '', 160)
        stamp = ', '.join(l.get('prefix', '') for l in k.get('launches', [])[:1])
    if k.get('kind') == 'healthy' or (book.v3.get(case) or {}).get('healthy'):
        return q, 'healthy; launch %s' % stamp
    summ = ((k.get('mechanism') or {}).get('summary') or '')
    return q, '%s; launch %s' % (clip(summ, 200), stamp)


def case_order(d, fam):
    if fam == 'C':
        return [c['id'] for c in d['real'].get('cases', [])]
    return [c['id'] for c in d['v3'].get('cases', [])]


def cases_table(d, fam, runs, title):
    runs = [r for r in runs if r['family'] == fam]
    if not runs:
        return ''
    models = sorted(set(r.get('model') for r in runs))
    cols = sorted(set((r['arm'], r.get('model')) for r in runs), key=lambda x: (arm_key(x[0]), x[1] or ''))
    head = ['Case', 'Asked; key'] + [a if len(models) < 2 else '%s (%s)' % (a, m) for a, m in cols]
    order = case_order(d, fam)
    cases = [c for c in order if any(r['case'] == c for r in runs)] + sorted(set(r['case'] for r in runs) - set(order))
    rows = []
    for c in cases:
        q, k = case_info(d, fam, c)
        cells = ['<code>%s</code>' % E(c), '<div class="keytxt">%s<br>%s</div>' % (E(q), E(k))]
        for a, m in cols:
            rs = sorted([r for r in runs if r['case'] == c and r['arm'] == a and r.get('model') == m],
                        key=lambda r: (r.get('repeat') or 0, r['batch']))
            cells.append(''.join(chip(r) for r in rs) or '<span class="muted">-</span>')
        rows.append(cells)
    return '<h3>%s</h3>%s' % (E(title), table(head, rows))


def cases_section(d):
    body = ['<p class="muted">One mark per run, in repeat order (hover or long-press for the run id). Fault cases: '
            '<span class="m pass">cause</span> Cause passed (Located included), <span class="m part">located</span> the '
            'keyed launch but not the cause, <span class="m fail">missed</span> not located. Healthy cases: '
            '<span class="m pass">clean</span> or <span class="m pass">benign</span> (a defect noted as harmless) on the '
            'keyed launch, <span class="m part">clean, not located</span> on another launch, <span class="m fail">false alarm</span>. '
            '<span class="m na">error</span>: the run or its scoring failed.</p>']
    for fam in ('B', 'C', 'A'):
        body.append(cases_table(d, fam, d['pilot_runs'], 'Family %s: %s' % (fam, label_family(d['preds'], fam))))
    if d['m0']:
        body.append(cases_table(d, 'A', d['m0']['runs'], 'Family A at M0, the P2 control runs (%s)' % (
            'fixed key' if d['m0'].get('fixed') else 'keys as run')))
    return section('cases', 'Every case', ''.join(body))


# --- missed

def fact_items(run, d):
    s = run.get('s') or {}
    f = s.get('facts') or {}
    o = s.get('outcome') or {}
    if not s:
        return [('scored', run.get('error') or 'not scored', False)]
    items = []
    key = d['book'].key(run['case'], run.get('mode') or 'm0') or {}
    stamp = ', '.join(l.get('prefix', '') for l in key.get('launches', [])[:1])
    loc = run.get('located')
    concl = (f.get('conclusion') or {}).get('launch')
    ltxt = 'yes' if loc else 'no'
    if concl:
        ltxt += '; concluded about %s %s (%s)' % (concl.get('date') or '', concl.get('time') or '', concl.get('tz') or '')
    elif 'conclusion' in f:
        ltxt += '; no launch concluded about'
    if stamp:
        ltxt += '; key %s' % stamp
    if f.get('keyed_named_anywhere') and not loc:
        ltxt += '; names the keyed launch elsewhere'
    items.append(('located', run_text(run, ltxt), bool(loc)))
    if run.get('healthy'):
        items.append(('outcome', o.get('outcome') or 'n/a', o.get('outcome') != 'false-alarm'))
        cg = f.get('causes_given') or []
        if cg and o.get('outcome') == 'false-alarm':
            items.append(('blamed', run_text(run, '%s in %s' % (cg[0].get('component') or '?', cg[0].get('stage') or '?'), 120), False))
        return items
    items.append(('report verdict', f.get('verdict_kind') or 'n/a', f.get('verdict_kind') == 'fault'))
    kc, ks = (key.get('component') or {}).get('name'), (key.get('stage') or {}).get('name')
    items.append(('component', run_text(run, 'said %s; key %s' % (f.get('component_said') or 'none', kc), 120), bool(f.get('component'))))
    items.append(('stage', run_text(run, 'said %s; key %s' % (f.get('stage_said') or 'none', ks), 120), bool(f.get('stage'))))
    mech = s.get('mechanism') or {}
    if mech.get('votes'):
        votes = mech['votes']
        items.append(('mechanism', '%s (votes: %s)' % (mech.get('verdict'), ', '.join('%s %d' % (v, votes.count(v)) for v in sorted(set(votes)))),
                      mech.get('verdict') == 'accepted'))
    elif mech.get('verdict'):
        items.append(('mechanism', str(mech['verdict']), None))
    return items


def missed_section(d):
    nb = d['nb']
    runs = [r for r in d['pilot_runs'] if r['arm'] != 'starved' and mark(r)[0] != 'pass']
    starved_ok = [r for r in d['pilot_runs'] if r['arm'] == 'starved' and score_of(r)]
    body = ['<p class="muted">Every pilot run that did not pass, grouped by case: its arm, run id, the facts the scorer '
            'checked (failed ones in red) and the opening of its report (at most %d characters; family C at most %d, with '
            'lines naming people, home folders or e-mail addresses dropped). Starved runs are left out (that control is '
            'meant to fail); starved runs that passed: %s.</p>' % (
                QUOTE_MAX, QUOTE_MAX_C, ', '.join('<code>%s</code>' % E(rid(r, nb)) for r in starved_ok) or 'none')]
    for fam in ('B', 'C', 'A'):
        for case in case_order(d, fam) + sorted(set(r['case'] for r in runs if r['family'] == fam) - set(case_order(d, fam))):
            rs = [r for r in runs if r['family'] == fam and r['case'] == case]
            if not rs:
                continue
            q, k = case_info(d, fam, case)
            part = ['<div class="case"><div class="case-head"><code>%s</code><span class="muted">family %s, %s</span></div>'
                    '<div class="key"><b>Key:</b> %s</div>' % (E(case), E(fam), E(q), E(k))]
            for r in sorted(rs, key=lambda r: (arm_key(r['arm']), r.get('model') or '', r.get('repeat') or 0, r['batch'])):
                facts = ''.join('<li>%s: <span class="%s">%s</span></li>' % (E(lab), 'ok' if ok else ('no' if ok is False else ''), E(txt))
                                for lab, txt, ok in fact_items(r, d))
                quote = conclusion_quote(read_text(os.path.join(r['dir'], 'final.md')), r['family'])
                part.append('<div class="miss"><div class="miss-head"><b>%s</b>%s<code>%s</code>%s</div><ul class="facts">%s</ul>%s</div>' % (
                    E(r['arm']), (' <span class="muted">(%s)</span> ' % E(r.get('model') or '')) if r.get('model') != d['model'] else ' ',
                    E(rid(r, nb)), chip(r), facts, ('<div class="quote">%s</div>' % E(quote)) if quote else ''))
            part.append('</div>')
            body.append(''.join(part))
    return section('missed', 'Cases an arm missed (%d runs)' % len(runs), ''.join(body))


# --- usage

def usage_section(d):
    rows, ag_t, sc_t = [], 0.0, 0.0
    for b in d['batches']:
        if b['kind'] == 'pilot':
            u = b['usage']
            ag = u.get('agent_usd')
            if ag is None:
                ag = sum(r.get('cost_usd') or 0 for r in b['runs'])
            sc = u.get('scorer_usd')
            if sc is None:
                sc = sum(r.get('scorer_usd') or 0 for r in b['runs'])
            rows.append(['<code>%s</code>' % E(b['id']), 'pilot', str(len(b['runs'])), usd(ag), usd(sc),
                         usd(u.get('scorer_fresh_usd_this_call')), usd(ag + sc)])
        else:
            ag = sum(r.get('cost_usd') or 0 for r in b['orig'])
            sc = b['orig_meta'].get('scorer_cost_usd') or 0.0
            fr = (b.get('fixed_meta') or {}).get('fresh_cost_usd_this_run')
            rows.append(['<code>%s</code>' % E(b['id']), 'M0 controls', str(len(b['orig'])), usd(ag),
                         usd(sc) + (' + %s re-score (fixed key)' % usd(fr) if fr is not None else ''),
                         usd(b['orig_meta'].get('fresh_cost_usd_this_run')), usd(ag + sc + (fr or 0))])
            sc += fr or 0
        ag_t += ag
        sc_t += sc
    rows.append(['<b>Total</b>', '', str(sum(len(b['runs']) for b in d['batches'])), '<b>%s</b>' % usd(ag_t), '<b>%s</b>' % usd(sc_t), '',
                 '<b>%s</b>' % usd(ag_t + sc_t)])
    body = [table(['Batch', 'Kind', 'Runs', 'Agent', 'Scorer (cached calls at first cost)', 'Scorer, fresh in the last call', 'Total'],
                  rows, (2, 3, 4, 5, 6))]
    u = (d['preds'].get('definitions') or {}).get('scores', {}).get('Usage')
    if u:
        body.append('<p class="muted">Usage: %s</p>' % E(u))
    p8 = pred(d['preds'], 'P8-usage')
    if p8.get('expected'):
        body.append('<p class="muted">P8 expected (descriptive): %s. Rule: %s</p>' % (E(p8['expected']), E(p8.get('rule', ''))))
    return section('usage', 'Usage', ''.join(body))


# ---------------------------------------------------------------------------------------------------------------

def build(d):
    return ''.join(['<title>%s</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n' % E(d['title']), FONTS,
                    '<style>%s</style>\n<div class="page">' % CSS, header(d),
                    section('findings', 'Headline findings', findings(d)), verdict_section(d), arms_section(d),
                    controls_section(d), cases_section(d), missed_section(d), usage_section(d), '</div>\n'])


def gather(a):
    preds = read_json(a.predictions)
    v3, real = read_json(a.cases_v3), read_json(a.cases_real)
    book = score.KeyBook(score.load_keys(a.keys), v3, real)
    pilots = [load_pilot(p) for p in a.pilot]
    m0 = load_m0(a.m0) if a.m0 else None
    pilot_runs = [r for b in pilots for r in b['runs']]
    warnings = [w for b in pilots + ([m0] if m0 else []) for w in b['warnings']]
    seen = {}
    for r in pilot_runs:
        seen.setdefault(r['run_id'], []).append(r['batch'])
    dup = sorted(k for k, v in seen.items() if len(v) > 1)
    if dup:
        warnings.append('%d run id(s) occur in more than one batch (shown as batch:run id): %s' % (len(dup), ', '.join(dup)))
    errs = [r['run_id'] for r in pilot_runs if r.get('error')]
    if errs:
        warnings.append('%d pilot run(s) have an error or were not scored: %s' % (len(errs), ', '.join(errs)))
    computed = run_verdict(pilot_runs, a.model)
    if a.verdict:
        verdict = read_json(a.verdict)
        warnings += verdict_diffs(verdict, computed)
    else:
        verdict = computed
    p2 = []
    if m0:
        vp2 = verdict.get('P2_controls_M0_haiku') or computed.get('P2_controls_M0_haiku')
        for tag, runs in (('keys as run', m0['orig']), ('fixed key', m0.get('fixed'))):
            if runs is None:
                continue
            model = sorted(set(r['model'] for r in runs))
            p2.append((tag, verdict_mod.controls(runs, 'A', 'm0', model[0] if len(model) == 1 else 'haiku', 'crib',
                                          vp2['positive_margin_needed'], vp2['negative_margin_needed'])))
    scorer_meta = (pilots[0]['scored_meta'] if pilots and pilots[0]['scored_meta'] else (m0 or {}).get('orig_meta', {}))
    batches = pilots + ([m0] if m0 else [])
    return {'preds': preds, 'v3': v3, 'real': real, 'book': book, 'batches': batches, 'pilot_runs': pilot_runs, 'm0': m0,
            'all_runs': pilot_runs + (m0['runs'] if m0 else []), 'verdict': verdict, 'verdict_given': bool(a.verdict),
            'warnings': warnings, 'p2': p2, 'model': a.model, 'commit': a.commit, 'title': a.title, 'notes': a.note,
            'scorer_meta': scorer_meta, 'nb': len(pilots)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pilot', action='append', required=True, help='a pilot.py results folder (repeatable)')
    ap.add_argument('--m0', help='the M0 Haiku control folder (scored.json, scored-keyfix.json)')
    ap.add_argument('--verdict', help="verdict.py's output JSON on the pilot rows")
    ap.add_argument('--predictions', required=True, help='the pre-registered predictions JSON')
    ap.add_argument('--commit', required=True, help='the commit SHA the runs used')
    ap.add_argument('--model', default='default', help='model flag of the verdict runs (default %(default)s)')
    ap.add_argument('--cases-v3', default=os.path.join(HERE, 'cases_v3.json'))
    ap.add_argument('--cases-real', default=os.path.join(HERE, 'cases_real.json'))
    ap.add_argument('--keys', default=os.path.join(HERE, 'keys_v3.json'))
    ap.add_argument('--title', default='DAQ Eval v3 Results')
    ap.add_argument('--note', action='append', default=[], help='a line of text under the header (repeatable)')
    ap.add_argument('--out', required=True, help='the HTML file to write')
    a = ap.parse_args(argv)
    d = gather(a)
    page = build(d)
    with open(a.out, 'w') as f:
        f.write(page)
    for w in d['warnings']:
        print('check: %s' % w, file=sys.stderr)
    print('wrote %s: %d pilot runs in %d batch(es), %d M0 runs, %d checks to look at'
          % (a.out, len(d['pilot_runs']), d['nb'], len(d['m0']['runs']) if d['m0'] else 0, len(d['warnings'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
