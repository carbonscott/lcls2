"""split.py NAME STEP_STARTS... : write rec/NAME-p<k>/frames.jsonl, one part per range of steps (by the step's first typed frame)."""
import json, os, re, sys, datetime
name = sys.argv[1]; starts = [int(x) for x in sys.argv[2:]]
fr = [json.loads(l) for l in open(f'rec/{name}/frames.jsonl')]
steps = json.load(open(f'steps/{name}.json'))
# a step starts at the first frame whose screen contains the beginning of its typed text on the last non-empty line
def first_frame(k, lo):
    key = steps[k]['send'][:12]
    for i in range(lo, len(fr)):
        lines = [l for l in re.sub(r'\x1b\[[0-9;:]*m', '', fr[i]['screen']).split('\n') if l.strip()]
        if lines and key in lines[-1]:
            return i
    return None
idx = []
lo = 0
for k in starts:
    i = first_frame(k, lo); idx.append(i); lo = i
idx[0] = 0
idx.append(len(fr))
for p, (a, b) in enumerate(zip(idx, idx[1:]), 1):
    d = f'rec/{name}-p{p}'; os.makedirs(d, exist_ok=True)
    with open(f'{d}/frames.jsonl', 'w') as f:
        for x in fr[a:b]:
            f.write(json.dumps(x) + '\n')
    print(f'{d}: frames {a}..{b-1} ({b-a}), steps from {starts[p-1]}')
