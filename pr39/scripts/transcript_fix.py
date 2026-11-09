#!/usr/bin/env python3
"""rec/NAME/transcript.txt -> rec/NAME/transcript.clean.txt: each command line is replaced by the exact text
recdrive typed (from the step file), which removes readline's redraw artifacts at line wraps.
usage: transcript_fix.py NAME STEPS.json"""
import json, re, sys
name, steps = sys.argv[1], json.load(open(sys.argv[2]))
lines = open(f'rec/{name}/transcript.txt').read().split('\n')
prompt = re.compile(r'^(.*?(?:exedev@indigo-galaxy|cwang31@sdf[a-z0-9]+):\S*\$ )(.*)$')
k, out, fixed = 0, [], 0
for ln in lines:
    m = prompt.match(ln)
    if m and k < len(steps) and m.group(2)[:15] == steps[k]['send'][:15]:
        if m.group(2) != steps[k]['send']:
            fixed += 1
        ln = m.group(1) + steps[k]['send']
        k += 1
    out.append(ln)
open(f'rec/{name}/transcript.clean.txt', 'w').write('\n'.join(out))
print(f'rec/{name}/transcript.clean.txt: {k}/{len(steps)} command lines matched, {fixed} repaired')
