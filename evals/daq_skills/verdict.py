#!/usr/bin/env python3
"""verdict.py: read the pre-registered verdicts (predictions P2-P6) from a table of scored runs.

Input: a JSON list of rows, one per scored run:
  {run_id, family ('A'|'B'|'C'), case, arm, mode ('m0'|'m1'), model, repeat,
   healthy (bool), cause_pass (bool|None), healthy_outcome ('clean'|'benign-defect-noted'|'false-alarm'|None),
   located (bool|None), calls (int|None: calls to evidence, censored runs already total+1),
   cost_usd, seconds}
'score' of a run = cause_pass for a fault case; healthy_outcome != 'false-alarm' for a healthy case.

Rules are copied from .goal/daq-skill-eval-v3.predictions.json (written before any run):
  P2/P3 controls: positive >= none + margin (points), negative <= none - 25 points on the same fault pools.
  P4/P5 G real: one-sided paired Wilcoxon signed-rank p < 0.05 on calls (none > pointer), pairs = (case, repeat);
        or Located gap >= 37.5% of runs.
  P6: shares on the primary metric (calls if G_calls real, else Located if G_loc real), noise floor from the bare
      cell's repeat 1 vs repeat 2; SUPPORTED if share(map) >= 0.5 and share(skills) <= 0.2; REFUTED if
      share(skills) >= share(map) or share(map) <= 0.2; else NO ANSWER. Overall: agree -> that; one NO ANSWER ->
      the other ('from one family'); SUPPORTED vs REFUTED -> NO ANSWER (families conflict).
Standard library only.
"""
import itertools
import json
import sys
from collections import defaultdict


def score(r):
    if r.get('healthy'):
        return None if r.get('healthy_outcome') is None else r['healthy_outcome'] != 'false-alarm'
    return r.get('cause_pass')


def rate(rows, f=score):
    v = [f(r) for r in rows]
    v = [x for x in v if x is not None]
    return (sum(1 for x in v if x), len(v))


def wilcoxon_greater(d):
    """Exact one-sided Wilcoxon signed-rank p-value for H1: median(d) > 0. Zeros dropped, ties get mid-ranks."""
    d = [x for x in d if x != 0]
    n = len(d)
    if n == 0:
        return 1.0, 0
    a = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[a[j + 1]]) == abs(d[a[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[a[k]] = (i + j) / 2.0 + 1
        i = j + 1
    w = sum(ranks[i] for i in range(n) if d[i] > 0)
    if n <= 20:
        cnt = tot = 0
        for signs in itertools.product((0, 1), repeat=n):
            tot += 1
            if sum(r for r, s in zip(ranks, signs) if s) >= w - 1e-9:
                cnt += 1
        return cnt / tot, n
    import math
    mu = n * (n + 1) / 4.0
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    z = (w - 0.5 - mu) / sd
    return 0.5 * math.erfc(z / math.sqrt(2)), n


def cell(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def controls(rows, family, mode, model, pos, margin_pos, margin_neg=25.0):
    base = cell(rows, family=family, mode=mode, model=model, arm='none')
    p = cell(rows, family=family, mode=mode, model=model, arm=pos)
    s = cell(rows, family=family, mode=mode, model=model, arm='starved')
    fault_cases = {r['case'] for r in s}
    base_f = [r for r in base if r['case'] in fault_cases]
    bk, bn = rate(base)
    pk, pn = rate(p)
    sk, sn = rate(s)
    bfk, bfn = rate(base_f)
    pct = lambda k, n: 100.0 * k / n if n else float('nan')
    out = {
        'none': [bk, bn, pct(bk, bn)], pos: [pk, pn, pct(pk, pn)],
        'none_on_starved_pools': [bfk, bfn, pct(bfk, bfn)], 'starved': [sk, sn, pct(sk, sn)],
        'positive_margin_needed': margin_pos, 'negative_margin_needed': margin_neg,
    }
    out['positive_pass'] = bool(pn and bn and pct(pk, pn) >= pct(bk, bn) + margin_pos)
    out['negative_pass'] = bool(sn and bfn and pct(sk, sn) <= pct(bfk, bfn) - margin_neg)
    out['detects_difference'] = out['positive_pass'] and out['negative_pass']
    return out


def family_verdict(rows, family, model, loc_threshold=0.375):
    m1 = cell(rows, family=family, mode='m1', model=model)
    by = defaultdict(dict)
    for r in m1:
        by[(r['case'], r['repeat'])][r['arm']] = r
    pairs = [(k, v) for k, v in sorted(by.items()) if 'none' in v and 'pointer' in v]
    res = {'family': family, 'pairs': len(pairs)}
    # G on calls
    d = [v['none']['calls'] - v['pointer']['calls'] for _, v in pairs
         if v['none'].get('calls') is not None and v['pointer'].get('calls') is not None]
    p, nz = wilcoxon_greater(d)
    res['G_calls'] = mean(d)
    res['G_calls_p'] = p
    res['G_calls_nonzero_pairs'] = nz
    res['G_calls_real'] = p < 0.05
    loc = lambda arm: rate(cell(m1, arm=arm), f=lambda r: r.get('located'))
    lk_none, ln_none = loc('none')
    lk_ptr, ln_ptr = loc('pointer')
    res['located'] = {a: list(loc(a)) for a in ('none', 'skills', 'map', 'both', 'pointer')}
    gap = (lk_ptr / ln_ptr - lk_none / ln_none) if ln_ptr and ln_none else 0.0
    res['G_loc'] = gap
    res['G_loc_real'] = gap >= loc_threshold
    calls = {a: mean([r.get('calls') for r in cell(m1, arm=a)]) for a in ('none', 'skills', 'map', 'both', 'pointer')}
    res['calls'] = calls
    if res['G_calls_real']:
        metric = 'calls'
        g = calls['none'] - calls['pointer']
        diff = lambda a: None if calls[a] is None or calls['none'] is None else calls['none'] - calls[a]   # an arm not run: no share
        r1 = mean([r.get('calls') for r in cell(m1, arm='none', repeat=1)])
        r2 = mean([r.get('calls') for r in cell(m1, arm='none', repeat=2)])
    elif res['G_loc_real']:
        metric = 'located'
        lr = lambda a, **kw: (lambda k, n: k / n if n else None)(*rate(cell(m1, arm=a, **kw), f=lambda r: r.get('located')))
        g = lr('pointer') - lr('none')
        diff = lambda a: None if lr(a) is None or lr('none') is None else lr(a) - lr('none')
        r1, r2 = lr('none', repeat=1), lr('none', repeat=2)
    else:
        res.update(primary=None, verdict='NO ANSWER', why='G not real on calls or Located')
        return res
    floor = abs((r1 or 0) - (r2 or 0))
    shares = {}
    for a in ('skills', 'map', 'both'):
        dv = diff(a)
        shares[a] = (dv / g) if (dv is not None and abs(dv) > floor and g) else 0.0
    res.update(primary=metric, G=g, noise_floor=floor, shares=shares)
    sm, ss = shares['map'], shares['skills']
    if sm >= 0.5 and ss <= 0.2:
        v, why = 'SUPPORTED', 'map share >= 0.5 and skills share <= 0.2'
    elif ss >= sm or sm <= 0.2:
        v, why = 'REFUTED', 'skills share >= map share' if ss >= sm else 'map share <= 0.2'
    else:
        v, why = 'NO ANSWER', 'between thresholds'
    res.update(verdict=v, why=why)
    return res


def overall(vb, vc):
    a, b = vb['verdict'], vc['verdict']
    if a == b:
        return a, 'both families agree'
    if a == 'NO ANSWER':
        return b, 'from one family (C real-MFX)'
    if b == 'NO ANSWER':
        return a, 'from one family (B sim-tree)'
    return 'NO ANSWER', 'families conflict (%s vs %s)' % (a, b)


def main(path, model_default='default', model_m0='haiku'):
    rows = json.load(open(path))
    out = {
        'P2_controls_M0_haiku': controls(rows, 'A', 'm0', model_m0, 'crib', 20.0),
        'P3_controls_M1_default': controls(rows, 'B', 'm1', model_default, 'pointer', 12.5),
        'P4_B': family_verdict(rows, 'B', model_default, 0.375),
        'P5_C': family_verdict(rows, 'C', model_default, 0.375),
    }
    out['P6_overall'] = overall(out['P4_B'], out['P5_C'])
    print(json.dumps(out, indent=1, default=str))


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        assert abs(wilcoxon_greater([1, 2, 3, 4, 5])[0] - 1 / 32) < 1e-9
        assert wilcoxon_greater([0, 0])[0] == 1.0
        assert abs(wilcoxon_greater([-1, 2, 3])[0] - 2 / 8) < 1e-9
        print('selftest ok')
    else:
        main(*sys.argv[1:])
