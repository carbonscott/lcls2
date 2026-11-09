#!/usr/bin/env python3
"""Render rec/NAME/frames.jsonl (tmux pane snapshots with ANSI colours) to a GIF.

usage: render.py NAME [--title T] [--idle 1.2] [--hold 4] [--from-regex R] [--out FILE]
Each snapshot is drawn as HTML by headless Chromium, then ffmpeg joins the PNGs with their
real durations, each capped at --idle seconds (so waits are shortened, never reordered).
"""
import html, json, os, re, shutil, subprocess, sys, tempfile
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = os.path.expanduser('~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome')

BASE16 = ['#1d1f21', '#cc6666', '#8abe68', '#e6c547', '#81a2be', '#b294bb', '#70c0ba', '#c5c8c6',
          '#666666', '#ff3334', '#9ec400', '#f0c674', '#81a2be', '#b77ee0', '#54ced6', '#ffffff']


def c256(n):
    if n < 16:
        return BASE16[n]
    if n < 232:
        n -= 16
        r, g, b = n // 36, (n // 6) % 6, n % 6
        f = lambda v: 0 if v == 0 else 55 + v * 40
        return '#%02x%02x%02x' % (f(r), f(g), f(b))
    v = 8 + (n - 232) * 10
    return '#%02x%02x%02x' % (v, v, v)


SGR = re.compile(r'\x1b\[([0-9;:]*)m')
OTHER = re.compile(r'\x1b\][^\x07]*\x07|\x1b[()][0-9A-Za-z]|\x1b\[[0-9;?]*[A-Za-ln-z]')


def ansi_to_html(text):
    st = dict(fg=None, bg=None, b=False, dim=False, it=False, ul=False, rev=False)
    out = []

    def span(s):
        if not s:
            return
        fg, bg = st['fg'], st['bg']
        if st['rev']:
            fg, bg = (bg or '#1d1f21'), (fg or '#c5c8c6')
        css = []
        if fg: css.append('color:' + fg)
        if bg: css.append('background:' + bg)
        if st['b']: css.append('font-weight:bold')
        if st['dim']: css.append('opacity:.7')
        if st['it']: css.append('font-style:italic')
        if st['ul']: css.append('text-decoration:underline')
        s = html.escape(s)
        out.append(f'<span style="{";".join(css)}">{s}</span>' if css else s)

    pos = 0
    text = OTHER.sub('', text)
    for m in SGR.finditer(text):
        span(text[pos:m.start()])
        pos = m.end()
        codes = [int(c) if c.isdigit() else 0 for c in re.split('[;:]', m.group(1) or '0')]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0: st.update(fg=None, bg=None, b=False, dim=False, it=False, ul=False, rev=False)
            elif c == 1: st['b'] = True
            elif c == 2: st['dim'] = True
            elif c == 3: st['it'] = True
            elif c == 4: st['ul'] = True
            elif c == 7: st['rev'] = True
            elif c == 22: st['b'] = st['dim'] = False
            elif c == 23: st['it'] = False
            elif c == 24: st['ul'] = False
            elif c == 27: st['rev'] = False
            elif 30 <= c <= 37: st['fg'] = BASE16[c - 30]
            elif 90 <= c <= 97: st['fg'] = BASE16[c - 90 + 8]
            elif 40 <= c <= 47: st['bg'] = BASE16[c - 40]
            elif 100 <= c <= 107: st['bg'] = BASE16[c - 100 + 8]
            elif c == 39: st['fg'] = None
            elif c == 49: st['bg'] = None
            elif c in (38, 48) and i + 1 < len(codes):
                key = 'fg' if c == 38 else 'bg'
                if codes[i + 1] == 5 and i + 2 < len(codes):
                    st[key] = c256(codes[i + 2]); i += 2
                elif codes[i + 1] == 2 and i + 4 < len(codes):
                    st[key] = '#%02x%02x%02x' % tuple(codes[i + 2:i + 5]); i += 4
            i += 1
    span(text[pos:])
    return ''.join(out)


PAGE = """<!doctype html><html><head><meta charset=utf-8><style>
body{margin:0;background:#2b2b2b}
#win{display:inline-block;background:#1d1f21;border-radius:8px;overflow:hidden;margin:0}
#bar{background:#3a3a3a;color:#ddd;font:13px 'DejaVu Sans',sans-serif;padding:6px 12px;white-space:pre}
#bar b{color:#fff}
pre{margin:0;padding:8px 10px;color:#c5c8c6;font:13px/1.25 'DejaVu Sans Mono',monospace;width:%(w)dch;height:%(h)dem;white-space:pre;overflow:hidden}
</style></head><body><div id=win><div id=bar>%(title)s</div><pre id=t></pre></div></body></html>"""


def main():
    name = sys.argv[1]
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    title = arg('--title', name)
    idle = float(arg('--idle', '1.2'))
    hold = float(arg('--hold', '4'))
    done_hold = float(arg('--done-hold', '2.5'))
    cols = int(arg('--cols', '140'))
    rows = int(arg('--rows', '40'))
    src = os.path.join(HERE, 'rec', name, 'frames.jsonl')
    out = arg('--out', os.path.join(HERE, 'rec', name, name + '.gif'))
    frames = [json.loads(l) for l in open(src)]
    td = tempfile.mkdtemp(prefix='render-')
    durs = []
    plain = lambda s: OTHER.sub('', SGR.sub('', s))
    for i, f in enumerate(frames):
        d = (frames[i + 1]['t'] - f['t']) if i + 1 < len(frames) else hold
        d = max(0.05, min(d, idle))
        lines = [l for l in plain(f['screen']).split('\n') if l.strip()]
        if lines and re.search(r'[$#] *$', lines[-1]) and i + 1 < len(frames):
            d = max(d, done_hold)                  # a finished output: hold it so it can be read
        durs.append(d if i + 1 < len(frames) else hold)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = b.new_page(device_scale_factor=1)
        pg.set_content(PAGE % dict(w=cols, h=rows * 1.25, title=html.escape(title)))
        el = pg.locator('#win')
        for i, f in enumerate(frames):
            pg.evaluate('h => document.getElementById("t").innerHTML = h', ansi_to_html(f['screen'].rstrip('\n')))
            el.screenshot(path=os.path.join(td, f'f{i:05d}.png'))
        b.close()
    lst = os.path.join(td, 'list.txt')
    with open(lst, 'w') as fh:
        for i, d in enumerate(durs):
            fh.write(f"file 'f{i:05d}.png'\nduration {d:.3f}\n")
        fh.write(f"file 'f{len(frames)-1:05d}.png'\n")
    vf = 'fps=8,split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-vf', vf, '-loop', '0', out], check=True)
    total = sum(durs)
    print(f'{out}: {len(frames)} frames, {total:.0f} s, {os.path.getsize(out)/1e6:.2f} MB')
    shutil.rmtree(td)


main()
