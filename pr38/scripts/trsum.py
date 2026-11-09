#!/usr/bin/env python3
"""trsum.py TYPE LOG: the summary lines of one typerun.sh log (up, cycle, down of one type in one Slurm step)."""
import re, sys
T, path = sys.argv[1], sys.argv[2]
txt = open(path).read()


def g(rx, d='?'):
    m = re.search(rx, txt, re.M)
    return m.group(1) if m else d


job, step, host, head, dirty = g(r'job=(\S*)'), g(r'step=(\S*)'), g(r'^host=(\S+)'), g(r'head=(\w{9})'), g(r'dirty=(\d+)')
up, cy, dn = g(r'^UP_EXIT=(\d+)'), g(r'^CYCLE_EXIT=(\d+)'), g(r'^DOWN_EXIT=(\d+)')
down = 'down: clean' if re.search(r'daq_sim: down: clean', txt) else 'down: NOT clean'
left = g(r'^== leftovers: (.*)$')
print(f'{T:<11} step {step} {host} {head} dirty={dirty}: UP_EXIT={up} CYCLE_EXIT={cy} DOWN_EXIT={dn}, {down}, left: {left}')
cnt = [(k, g(r'^  ' + re.escape(k) + r'\s+(\S+)')) for k in ('simxpm NumL0Acc', 'TEB_WrtCt', 'psana2 events', 'psana2 with data', 'psana2 checks')]
res = g(r'^\S+ (cycle (?:PASS|FAIL))', 'no cycle result')
rej = len(re.findall(r'coverage would reject', txt))
print(f'{"":<11} ' + ', '.join(f'{k} {v}' for k, v in cnt) + f'; {res}' + (f'; coverage would reject: {rej} line(s)' if rej else ''))
print(f'{"":<11} ' + g(r'^\S+ (evidence \S+: .*)$', 'NO evidence line'))
