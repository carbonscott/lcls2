"""gui_lines.py GUI-PARITY.txt: check_gui_parity's output, compact: the walks it ran, then one line per file
(file | web path or N/A reason, cut to 56 characters | N/M/K | result), the PV check line, then the overall RESULT."""
import re, sys, textwrap
for ln in open(sys.argv[1]):
    ln = ln.rstrip('\n')
    m = re.match(r'^(\w+)( variant \d+)?(?: \[.*?\])?: (qt_walk .*?)(?: -> .*)?$', ln)
    if m:
        print('  %s%s: %s' % (m.group(1), m.group(2) or '', m.group(3).replace(', error None', '')))
        continue
    if ln.startswith('PV check of the pvgui pages'):
        print(textwrap.fill(ln, 136, subsequent_indent='    '))
        continue
    if ln.startswith(('walks:', 'file | ', 'RESULT: FAIL (', 'RESULT: PASS (')) or re.match(r'^\d+ psdaq files', ln):
        print(ln[:150])
        continue
    f = ln.split(' | ')
    if len(f) >= 4 and re.match(r'^[a-z_]+/', f[0]) and f[-1] in ('PASS', 'FAIL'):
        why = f[1] if len(f[1]) <= 56 else f[1][:53] + '...'
        print('%-39s | %-56s | %-14s | %s' % (f[0], why, f[-2].replace(' (source sites; no walk)', ' (src)'), f[-1]))
