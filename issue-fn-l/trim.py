#!/usr/bin/env python3
"""trim.py IN/frames.jsonl OUT/frames.jsonl: drop the frames before the first sdfiana025 prompt.

The recording is driven from a workstation that ssh-es to sdfiana025; rec_rc.sh clears the
screen on arrival, so the kept frames start at the cleared sdfiana025 prompt. No frame after
that point is changed, dropped or reordered.
"""
import json, re, sys
ANSI = re.compile(r'\x1b\][^\x07]*\x07|\x1b\[[0-9;:?]*[A-Za-z]|\x1b[()][0-9A-Za-z]')
frames = [json.loads(l) for l in open(sys.argv[1])]
first = next(i for i, f in enumerate(frames)
             if (lambda ls: ls and 'sdfiana025' in ls[0] and 'ssh -t' not in ANSI.sub('', f['screen']))(
                 [l for l in ANSI.sub('', f['screen']).split('\n') if l.strip()]))
with open(sys.argv[2], 'w') as fh:
    for f in frames[first:]:
        fh.write(json.dumps(f) + '\n')
print(f'kept {len(frames) - first} of {len(frames)} frames')
