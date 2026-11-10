#!/usr/bin/env python3
"""splitgif.py REC N OUT_A OUT_B: split part N of render_split's output (rec/REC/png/pN.txt) into two GIFs at its
middle frame, with render_split's ffmpeg passes (8 fps, 128 colours), so each stays under 6 MB."""
import os, subprocess, sys
rec, n, oa, ob = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
td = os.path.join('rec', rec, 'png')
lines = open(os.path.join(td, f'p{n}.txt')).read().split('\n')
pairs = []
for i in range(0, len(lines) - 1, 2):
    if lines[i].startswith('file') and i + 1 < len(lines) and lines[i + 1].startswith('duration'):
        pairs.append((lines[i], lines[i + 1]))
mid = len(pairs) // 2
for tag, part, out in (('a', pairs[:mid], oa), ('b', pairs[mid:], ob)):
    lst = os.path.join(td, f'p{n}{tag}.txt')
    with open(lst, 'w') as fh:
        for f, d in part:
            fh.write(f + '\n' + d + '\n')
        fh.write(part[-1][0] + '\n')
    pal = os.path.join(td, f'pp{n}{tag}.png')
    ff = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst]
    subprocess.run(ff + ['-vf', 'fps=8,palettegen=max_colors=128:stats_mode=full', pal], check=True)
    subprocess.run(ff + ['-i', pal, '-lavfi', 'fps=8[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle', '-loop', '0', out], check=True)
    print(f'{out}: {len(part)} frames, {os.path.getsize(out)} B')
