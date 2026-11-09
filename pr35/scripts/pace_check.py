#!/usr/bin/env python3
"""Check a browser driver's action log (paced_drive.py's actions.jsonl) against the pacing rules.

usage: pace_check.py ACTIONS.jsonl [--min-highlight 1.0] [--min-gap 2.5]
Prints the action count, min(act_time - highlight_start) and the smallest gap between consecutive
act_times, each from the log's own timestamps, and exits 0 only if both minimums meet the limits.
"""
import json, sys

path = sys.argv[1]
arg = lambda k, d: float(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
lim_hl, lim_gap = arg('--min-highlight', 1.0), arg('--min-gap', 2.5)
acts = [json.loads(l) for l in open(path) if l.strip()]
for a in acts:
    assert a['highlight_start'] <= a['act_time'] <= a['end'], a
acts.sort(key=lambda a: a['act_time'])
holds = [(a['act_time'] - a['highlight_start'], a['action']) for a in acts]
gaps = [(b['act_time'] - a['act_time'], b['action']) for a, b in zip(acts, acts[1:])]
h, ha = min(holds)
g, ga = min(gaps)
print(f'{path}: {len(acts)} actions')
print(f'  min(act_time - highlight_start) = {h:.3f} s  (at: {ha})')
print(f'  min gap between consecutive act_times = {g:.3f} s  (before: {ga})')
ok = h >= lim_hl and g >= lim_gap
print(f'ACTIONS={len(acts)}  MIN_HIGHLIGHT_TO_ACT={h:.3f} s  MIN_GAP_BETWEEN_ACTS={g:.3f} s  '
      f'{"PASS" if ok else "FAIL"} (limits: highlight >= {lim_hl} s, gap >= {lim_gap} s)')
sys.exit(0 if ok else 1)
