"""Write one self-contained HTML page of the graded results.

    python3 report.py --results RESULTS_DIR --out report.html [--title T] [--note TEXT ...]

The page has a per-arm summary, a per-tier breakdown, the full matrix (one row per case,
one column per arm, one mark per repeat) and, for every case where an arm did not get
'correct', the answer key next to what each arm concluded.  No scripts, no external files.
Standard library only, Python 3.6+.
"""

import argparse
import html
import json
import os
import sys

import grade

CSS = """
:root{--bg:#f6f7f9;--surface:#fff;--sunk:#eceff3;--line:#d5dae2;--fg:#1b2330;--muted:#5a6577;--accent:#2b4fa8;
--ok:#1d6b45;--ok-bg:#dff1e7;--part:#8a5a00;--part-bg:#f8ecd0;--bad:#a3271f;--bad-bg:#f9e0dd;--unk:#44506a;--unk-bg:#e4e8f0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12161d;--surface:#1a2029;--sunk:#0e1218;--line:#2e3745;
--fg:#e4e8ef;--muted:#98a3b5;--accent:#8fabf2;--ok:#7fd3a4;--ok-bg:#173526;--part:#ecc266;--part-bg:#3a2e10;--bad:#f19a92;
--bad-bg:#42201d;--unk:#b4bfd4;--unk-bg:#28303d;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#12161d;--surface:#1a2029;--sunk:#0e1218;--line:#2e3745;--fg:#e4e8ef;--muted:#98a3b5;
--accent:#8fabf2;--ok:#7fd3a4;--ok-bg:#173526;--part:#ecc266;--part-bg:#3a2e10;--bad:#f19a92;--bad-bg:#42201d;--unk:#b4bfd4;
--unk-bg:#28303d;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0}
.wrap{max-width:1040px;margin:0 auto;padding-block:28px 56px;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:30px}
h1{font-size:27px;margin:0;line-height:1.2}h2{font-size:19px;margin:0}section{display:flex;flex-direction:column;gap:12px}
p{margin:0;max-width:75ch}.muted{color:var(--muted);font-size:13.5px}code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}td.n,th.n{text-align:right}
tr.tier td{background:var(--sunk);font-weight:600;font-size:12.5px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.c{display:inline-block;font-size:12px;font-weight:600;border-radius:4px;padding:1px 7px;margin:1px 2px 1px 0;white-space:nowrap}
.correct{background:var(--ok-bg);color:var(--ok)}.partial{background:var(--part-bg);color:var(--part)}
.wrong,.false-alarm,.fail{background:var(--bad-bg);color:var(--bad)}.unknown,.error{background:var(--unk-bg);color:var(--unk)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.key{background:var(--sunk);border-radius:6px;padding:8px 10px;font-size:13.5px}
.duo{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.duo>div{min-width:0;font-size:13.5px}
.q{border-left:3px solid var(--line);padding-left:9px;color:var(--muted);overflow-wrap:anywhere}
"""
TIERS = {1: 'Tier 1: one launch, 3 to 5 processes', 2: 'Tier 2: one launch of a full partition, 23 to 36 processes',
         3: 'Tier 3: one node\'s day, 149 launches, older ones compressed'}
E = html.escape


def chip(v, text=None):
    return '<span class="c %s">%s</span>' % (v, E(text or v))


def cell(rs):
    out = []
    for r in sorted(rs, key=lambda r: r['repeat']):
        v = 'error' if r['error'] else r['cause']['verdict']
        out.append(chip(v, v + ('!' if r['cause']['overconfident'] else '')))
        if not r['readonly']['pass']:
            out.append(chip('fail', 'write: ' + r['readonly']['hard'][0]['what']))
        if r['routing']['pass'] is False:
            out.append(chip('partial', 'skills'))
    return ''.join(out) or '<span class="muted">not run</span>'


def build(rows, cases, title, notes):
    arms = sorted({r['arm'] for r in rows})
    summary = grade.summarize(rows)
    p = ['<title>%s</title><style>%s</style><div class="wrap">' % (E(title), CSS)]
    p.append('<header><h1>%s</h1>%s</header>' % (E(title), ''.join('<p class="muted">%s</p>' % E(n) for n in notes)))
    # summary
    p.append('<section><h2>Per arm</h2><div class="tbl"><table><tr><th>Arm</th><th class="n">Runs</th><th class="n">Correct</th>'
             '<th class="n">Partial</th><th class="n">Unknown</th><th class="n">Wrong</th><th class="n">False alarm</th>'
             '<th class="n">Read-only</th><th class="n">Skills loaded</th><th class="n">Right launch</th><th class="n">Known issue cited</th><th class="n">Template</th>'
             '<th class="n">Sure and wrong</th><th class="n">Mean time</th><th class="n">Mean usage*</th></tr>')
    for arm in arms:
        s = summary[arm]
        p.append('<tr><td><b>%s</b></td><td class="n">%d</td><td class="n"><b>%d</b></td><td class="n">%d</td><td class="n">%d</td>'
                 '<td class="n">%d</td><td class="n">%d</td><td class="n">%d/%d</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                 '<td class="n">%d/%d</td><td class="n">%d</td><td class="n">%s s</td><td class="n">$%s</td></tr>' % (
                     E(arm), s['runs'], s['correct'], s['partial'], s['unknown'], s['wrong'], s['false-alarm'], s['readonly'],
                     s['runs'], s['routing'], s['sessions'], s['known'], s['templated'], s['runs'], s['overconfident'], s['mean_seconds'],
                     s['mean_cost_usd']))
    judged = sum(s['judged'] for s in summary.values())
    p.append('</table></div><p class="muted">* API-equivalent cost reported by the CLI; on a subscription it measures usage, '
             'nothing is billed. Cause verdicts: %d of %d by the judge model, the rest by keywords.</p></section>'
             % (judged, sum(s['runs'] for s in summary.values())))
    # per tier
    p.append('<section><h2>Cause correct, by tier and by where the key came from</h2><div class="tbl"><table><tr><th>Group</th>'
             + ''.join('<th class="n">%s</th>' % E(a) for a in arms) + '</tr>')
    groups = [(TIERS[t], lambda r, t=t: r['tier'] == t) for t in sorted(TIERS)] + [
        ('Fault was planted by the sim', lambda r: r['key_source'] == 'planted' and not r['healthy']),
        ('Fault was a real failure, key from reviewed logs', lambda r: r['key_source'] == 'observed'),
        ('Healthy (no fault)', lambda r: r['healthy'])]
    for name, f in groups:
        p.append('<tr><td>%s</td>' % E(name))
        for arm in arms:
            rs = [r for r in rows if r['arm'] == arm and f(r) and not r['error']]
            p.append('<td class="n">%d / %d</td>' % (sum(r['cause']['verdict'] == 'correct' for r in rs), len(rs)))
        p.append('</tr>')
    p.append('</table></div></section>')
    # matrix
    p.append('<section><h2>Every case</h2><p class="muted">One mark per run. "!" means the report said Confidence: high and '
             'was wrong.</p><div class="tbl"><table><tr><th>Case</th><th>What happened (answer key)</th>'
             + ''.join('<th>%s</th>' % E(a) for a in arms) + '</tr>')
    order = [c for c in cases.values() if any(r['case'] == c['id'] for r in rows)]
    for t in sorted(TIERS):
        p.append('<tr class="tier"><td colspan="%d">%s</td></tr>' % (2 + len(arms), E(TIERS[t])))
        for c in [c for c in order if c['tier'] == t]:
            f = c['key'].get('fault')
            what = (f['summary'] if f else 'No fault') if not c['key'].get('launches') else f['summary']
            p.append('<tr><td><code>%s</code></td><td>%s</td>' % (E(c['id']), E(what[:150] + ('...' if len(what) > 150 else ''))))
            for arm in arms:
                p.append('<td>%s</td>' % cell([r for r in rows if r['arm'] == arm and r['case'] == c['id']]))
            p.append('</tr>')
    p.append('</table></div></section>')
    # details
    odd = [c for c in order if any(r['case'] == c['id'] and (r['error'] or r['cause']['verdict'] != 'correct' or
                                                           not r['readonly']['pass']) for r in rows)]
    p.append('<section><h2>Cases where an arm was not correct (%d)</h2>' % len(odd))
    for c in odd:
        f = c['key'].get('fault')
        p.append('<div class="card"><div><code>%s</code> &nbsp; <span class="muted">%s</span></div><div class="key"><b>Key:</b> %s</div>'
                 '<div class="duo">' % (E(c['id']), E(c['question']), E(f['summary'] if f else 'No fault.')))
        for arm in arms:
            for r in sorted([r for r in rows if r['arm'] == arm and r['case'] == c['id']], key=lambda r: r['repeat']):
                text = open(os.path.join(r['run_dir'], 'final.md'), errors='replace').read().strip()
                p.append('<div><b>%s</b> r%d %s<br><span class="muted">%s</span><div class="q">%s</div></div>' % (
                    E(arm), r['repeat'], cell([r]), E(r['cause'].get('reason') or ''), E(text[:420]) + ('...' if len(text) > 420 else '')))
        p.append('</div></div>')
    p.append('</section></div>')
    return ''.join(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--catalog', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'catalog.json'))
    ap.add_argument('--results', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', default='DAQ skill eval results')
    ap.add_argument('--note', action='append', default=[])
    a = ap.parse_args(argv)
    cases = grade.load_catalog(a.catalog)
    rows = grade.collect(a.results, cases)
    open(a.out, 'w').write(build(rows, cases, a.title, a.note))
    print('%s: %d runs, %d arms' % (a.out, len(rows), len({r['arm'] for r in rows})))
    return 0


if __name__ == '__main__':
    sys.exit(main())
