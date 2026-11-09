#!/usr/bin/env python3
"""rec/NAME/session.cast -> rec/NAME/transcript.txt (output events, terminal escapes removed)."""
import json, re, sys
name = sys.argv[1]
ev = [json.loads(l) for l in open(f'rec/{name}/session.cast')][1:]
txt = ''.join(e[2] for e in ev if e[1] == 'o')
txt = re.sub(r' \r(?!\n)', '', txt)
txt = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-Za-z]|\x1b[=>]|\r', '', txt)
# drop the per-keystroke echo noise: keep text as the terminal finally showed it
open(f'rec/{name}/transcript.txt', 'w').write(txt)
print(f'rec/{name}/transcript.txt: {len(txt.splitlines())} lines')
