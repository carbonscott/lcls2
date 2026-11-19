"""Screenshot chosen frames of rec/NAME/frames.jsonl as PNGs, with render.py's HTML (same look as the GIF)."""
import html, json, os, sys
sys.path.insert(0, os.path.expanduser('~/projects/lcls2/redo'))
import render
from playwright.sync_api import sync_playwright
name, title, picks = sys.argv[1], sys.argv[2], sys.argv[3:]   # picks: idx:outname
d = os.path.join(os.path.expanduser('~/projects/lcls2/redo/rec'), name)
fr = [json.loads(l) for l in open(os.path.join(d, 'frames.jsonl'))]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=render.CHROME, headless=True)
    pg = b.new_page(device_scale_factor=1)
    pg.set_content(render.PAGE % dict(w=160, h=48 * 1.25, title=html.escape(title)))
    for pk in picks:
        i, out = pk.split(':')
        pg.evaluate('h => document.getElementById("t").innerHTML = h', render.ansi_to_html(fr[int(i)]['screen'].rstrip('\n')))
        pg.locator('#win').screenshot(path=os.path.join(d, out))
        print(out)
    b.close()
