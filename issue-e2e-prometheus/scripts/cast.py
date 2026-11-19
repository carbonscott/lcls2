#!/usr/bin/env python3
"""typescript + timing (util-linux script, classic format) -> asciicast v2, with chapter markers.

usage: cast.py TYPESCRIPT TIMING CHAPTERS.jsonl COLS ROWS OUT.cast
The first line of TYPESCRIPT ("Script started on ...") is skipped; each timing line is
"<delay s> <bytes>". The start time is the header's time; markers come from CHAPTERS.jsonl
(epoch seconds), placed relative to the first output byte's wall time, which is read from the
typescript's own header (minute resolution in util-linux 2.32) refined by the driver's first
chapter not being before t=0.
"""
import json, sys


def main():
    ts, tm, ch, cols, rows, out = sys.argv[1:7]
    data = open(ts, 'rb').read()
    nl = data.index(b'\n') + 1
    header, body = data[:nl].decode(errors='replace').strip(), data[nl:]
    events, t, pos = [], 0.0, 0
    for line in open(tm):
        d, n = line.split()
        t += float(d)
        chunk = body[pos:pos + int(n)]
        pos += int(n)
        events.append([round(t, 6), 'o', chunk.decode('utf-8', errors='replace')])
    start = float(open(ch + '.start').read().split()[0])   # epoch of script start (written by rec.sh)
    marks = []
    for l in open(ch):
        c = json.loads(l)
        marks.append([round(c['t'] - start, 6), 'm', c['utc'][11:19] + 'Z ' + c['label']])
    allev = sorted(events + marks, key=lambda e: e[0])
    with open(out, 'w') as f:
        f.write(json.dumps({'version': 2, 'width': int(cols), 'height': int(rows), 'timestamp': int(start),
                            'idle_time_limit': 2, 'title': header}) + '\n')
        for e in allev:
            f.write(json.dumps(e) + '\n')
    print('cast: %d output events, %d markers, %.1f s, %d of %d bytes used' % (len(events), len(marks), t, pos, len(body)))


if __name__ == '__main__':
    main()
