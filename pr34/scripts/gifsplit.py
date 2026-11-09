#!/usr/bin/env python3
"""gifsplit.py NAME RENDER_TMP OUTDIR: split the GIF of rec/NAME into 3 parts, from the PNGs and
list.txt that render.py made in RENDER_TMP (one PNG per pane snapshot, with its duration).
Parts start at the snapshot where '# wave8' and then '# (d) a fault' are first typed. Each part is
joined with ffmpeg in two passes (palettegen, then paletteuse) at 8 fps and 128 colours, so no
whole-video frame buffer is needed. The single 300 s GIF was 10.6 MB; the parts are 3-4.4 MB."""
import json, os, re, subprocess, sys
name, tmp, out = sys.argv[1:4]
SGR = re.compile(r'\x1b\[[0-9;:]*m')
pl = [SGR.sub('', json.loads(l)['screen']) for l in open(f'rec/{name}/frames.jsonl')]
k1 = next(i for i, s in enumerate(pl) if re.search(r'\$ # wave8\s*$', s, re.M))
k2 = next(i for i, s in enumerate(pl) if '# (d) a fault' in s)
lines = open(os.path.join(tmp, 'list.txt')).read().split('\n')
pairs = [(lines[i], lines[i + 1]) for i in range(0, 2 * len(pl), 2)]
for n, sel in enumerate((pairs[:k1], pairs[k1:k2], pairs[k2:]), 1):
    lst = os.path.join(tmp, f'p{n}.txt')
    with open(lst, 'w') as fh:
        for j, (a, d) in enumerate(sel):
            fh.write(a + '\n' + ('duration 4.000' if j == len(sel) - 1 else d) + '\n')
        fh.write(sel[-1][0] + '\n')
    pal, gif = os.path.join(tmp, f'pp{n}.png'), os.path.join(out, f'terminal-{n}.gif')
    ff = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst]
    subprocess.run(ff + ['-vf', 'fps=8,palettegen=max_colors=128:stats_mode=full', pal], check=True)
    subprocess.run(ff + ['-i', pal, '-lavfi', 'fps=8[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle',
                         '-loop', '0', gif], check=True)
    print(gif, len(sel), 'frames', os.path.getsize(gif), 'B')
