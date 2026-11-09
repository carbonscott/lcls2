#!/usr/bin/env python3
"""render_split.py NAME OUTDIR --title T MARKER...: the GIFs of rec/NAME (run from redo/), one per part.

Reuses render.py's drawing (each tmux pane snapshot drawn as HTML by headless Chromium, its real
duration capped at 1.2 s, a finished output held 2.5 s). The frames are split where a MARKER
(a regex) first appears as a typed line at the shell prompt; each part is joined with ffmpeg in
two passes (palettegen, then paletteuse) at 8 fps and 128 colours, as gifsplit.py did for PR #34.
The PNGs and list.txt stay in rec/NAME/png/ so a part can be re-cut without redrawing."""
import json, os, re, subprocess, sys

HERE = os.path.abspath('.')
src = open(os.path.join(HERE, 'render.py')).read()
ns = {'__file__': os.path.join(HERE, 'render.py'), '__name__': 'render_lib'}
exec(compile(src.replace('\nmain()\n', '\n'), 'render.py', 'exec'), ns)

name, out = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
title = args[args.index('--title') + 1] if '--title' in args else name
if '--title' in args:
    k = args.index('--title'); del args[k:k + 2]
markers = args
idle, done_hold, hold, cols, rows = float(os.environ.get('RENDER_IDLE', 1.2)), float(os.environ.get('RENDER_DONE_HOLD', 2.5)), 4.0, 140, 40
frames = [json.loads(l) for l in open(f'rec/{name}/frames.jsonl')]
SGR, OTHER = ns['SGR'], ns['OTHER']
plain = [OTHER.sub('', SGR.sub('', f['screen'])) for f in frames]
durs = []
for i, f in enumerate(frames):
    d = (frames[i + 1]['t'] - f['t']) if i + 1 < len(frames) else hold
    d = max(0.05, min(d, idle))
    lines = [l for l in plain[i].split('\n') if l.strip()]
    if lines and re.search(r'[$#] *$', lines[-1]) and i + 1 < len(frames):
        d = max(d, done_hold)
    durs.append(d if i + 1 < len(frames) else hold)
td = os.path.join(HERE, 'rec', name, 'png')
os.makedirs(td, exist_ok=True)
if not os.path.exists(os.path.join(td, f'f{len(frames)-1:05d}.png')):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=ns['CHROME'], headless=True)
        pg = b.new_page(device_scale_factor=1)
        pg.set_content(ns['PAGE'] % dict(w=cols, h=rows * 1.25, title=ns['html'].escape(title)))
        el = pg.locator('#win')
        for i, f in enumerate(frames):
            pg.evaluate('h => document.getElementById("t").innerHTML = h', ns['ansi_to_html'](f['screen'].rstrip('\n')))
            el.screenshot(path=os.path.join(td, f'f{i:05d}.png'))
        b.close()
cuts = [0]
for m in markers:
    rx = re.compile(r'\$ ' + m, re.M)
    k = next(i for i, s in enumerate(plain) if i > cuts[-1] and rx.search(s))
    cuts.append(k)
cuts.append(len(frames))
os.makedirs(out, exist_ok=True)
for n in range(1, len(cuts)):
    a, b_ = cuts[n - 1], cuts[n]
    lst = os.path.join(td, f'p{n}.txt')
    with open(lst, 'w') as fh:
        for j in range(a, b_):
            fh.write(f"file 'f{j:05d}.png'\nduration {4.0 if j == b_ - 1 else durs[j]:.3f}\n")
        fh.write(f"file 'f{b_-1:05d}.png'\n")
    pal, gif = os.path.join(td, f'pp{n}.png'), os.path.join(out, f'terminal-{n}.gif')
    ff = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst]
    subprocess.run(ff + ['-vf', 'fps=8,palettegen=max_colors=128:stats_mode=full', pal], check=True)
    subprocess.run(ff + ['-i', pal, '-lavfi', 'fps=8[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle',
                         '-loop', '0', gif], check=True)
    print(f'{gif}: frames {a}..{b_-1} ({b_-a}), {sum(durs[a:b_]):.0f} s, {os.path.getsize(gif)} B')
