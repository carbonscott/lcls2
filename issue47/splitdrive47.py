#!/usr/bin/env python3
"""Record issue 47's reproduction as a two-pane terminal session, at a pace a reader can follow.

An outer headless tmux pane (the frame that is captured) runs an inner tmux with two panes, each an ssh
shell on sdfiana025: left "the code", right "the run".  Frames go to rec/NAME/frames.jsonl, as recdrive.py
writes them, so render.py turns them into a GIF.

Pacing, logged per action in rec/NAME/actions.jsonl:
  - commands are typed at TYPE_CPS characters a second;
  - a caption (a `# ...` line) stays READ_CAPTION seconds before the next command is typed;
  - after a command's output is complete it stays max(MIN_HOLD, BASE + PER_LINE * lines) seconds,
    or the step's own `hold`.
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = sys.argv[1] if len(sys.argv) > 1 else 'issue47b'
COLS, ROWS, LEFT = 152, 42, 64
TYPE_CPS, READ_CAPTION, MIN_HOLD, BASE, PER_LINE = 22, 3.0, 4.0, 2.0, 0.55
SHA = '39afa18e3f4f0b8735746f6d1eddc0bbbd32fd13'
OUT = os.path.join(HERE, 'rec', NAME)
os.makedirs(OUT, exist_ok=True)
OUTER = ['tmux', '-L', 'recsock', '-f', os.path.join(HERE, 'rec.tmux.conf')]
INNER = ['tmux', '-L', 'inner47', '-f', os.path.join(HERE, 'inner47.tmux.conf')]
SESS = 'rec-' + NAME
SSH = ("ssh -F %s/ssh_config -t sdfiana025 "
       "'bash --rcfile /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/issue47/rc2.sh -i'" % HERE)
PROMPT = re.compile(r'\$\s*$')


def run(cmd, check=False):
    return subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout


frames = open(os.path.join(OUT, 'frames.jsonl'), 'w')
actions = open(os.path.join(OUT, 'actions.jsonl'), 'w')
last = [None]


def snap():
    txt = run(OUTER + ['capture-pane', '-p', '-e', '-t', SESS])
    if txt and txt != last[0]:
        frames.write(json.dumps({'t': time.time(), 'screen': txt}) + '\n')
        frames.flush()
        last[0] = txt


def pane(p):
    return run(INNER + ['capture-pane', '-p', '-t', 'i.%d' % p])


def at_prompt(p):
    lines = [l for l in pane(p).split('\n') if l.strip()]
    return bool(lines) and bool(PROMPT.search(lines[-1]))


def hold(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        snap()
        time.sleep(0.2)


def wait(pred, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap()
        if pred():
            return True
        time.sleep(0.2)
    return False


def focus(p):
    run(INNER + ['select-pane', '-t', 'i.%d' % p])
    hold(1.5)


def do(p, text, hold_s=None, expect=None, timeout=120):
    """Type text into pane p, wait for its output, keep it on screen long enough to read."""
    before = len([l for l in pane(p).split('\n') if l.strip()])
    t_type = time.time()
    for ch in text:
        arg = '\\;' if ch == ';' else ch
        run(INNER + ['send-keys', '-t', 'i.%d' % p, '-l', '--', arg])
        snap()
        time.sleep(1.0 / TYPE_CPS)
    hold(0.6)                                   # the finished command line, before Enter
    run(INNER + ['send-keys', '-t', 'i.%d' % p, 'Enter'])
    t_enter = time.time()
    time.sleep(0.4)
    exp = re.compile(expect, re.M) if expect else None
    ok = wait(lambda: at_prompt(p) and (not exp or exp.search(pane(p))), timeout)
    t_done = time.time()
    if text.startswith('#'):
        h = READ_CAPTION if hold_s is None else hold_s
        lines = 0
    else:
        lines = max(0, len([l for l in pane(p).split('\n') if l.strip()]) - before - 1)
        h = max(MIN_HOLD, BASE + PER_LINE * lines) if hold_s is None else hold_s
    hold(h)
    actions.write(json.dumps({'pane': p, 'text': text, 'ok': ok, 'type_start': t_type, 'enter': t_enter,
                              'output_done': t_done, 'output_lines': lines, 'hold': time.time() - t_done}) + '\n')
    actions.flush()
    if not ok:
        print('TIMEOUT:', text)
        finish(2)


def finish(rc):
    hold(1)
    run(INNER + ['kill-server'])
    run(OUTER + ['kill-session', '-t', SESS])
    frames.close(); actions.close()
    acts = [json.loads(l) for l in open(os.path.join(OUT, 'actions.jsonl'))]
    cmds = [a for a in acts if not a['text'].startswith('#')]
    caps = [a for a in acts if a['text'].startswith('#')]
    if acts:
        print('ACTIONS=%d  MIN_HOLD_AFTER_OUTPUT=%.1f s  MIN_HOLD_AFTER_CAPTION=%.1f s  TOTAL=%.0f s' % (
            len(acts), min(a['hold'] for a in cmds), min(a['hold'] for a in caps),
            acts[-1]['output_done'] + acts[-1]['hold'] - acts[0]['type_start']))
    print('SPLITDRIVE_EXIT=%d' % rc)
    sys.exit(rc)


run(INNER + ['kill-server'])
run(OUTER + ['kill-session', '-t', SESS])
inner = ' '.join(INNER) + ' -u new-session -s i -x %d -y %d "%s"' % (COLS, ROWS, SSH)
run(OUTER + ['new-session', '-d', '-s', SESS, '-x', str(COLS), '-y', str(ROWS), 'env LANG=C.UTF-8 ' + inner], check=True)
time.sleep(2)
run(INNER + ['split-window', '-h', '-t', 'i.0', '-l', str(COLS - LEFT - 1), SSH], check=True)
if not (wait(lambda: at_prompt(0) and at_prompt(1), 60)):
    print('no prompts'); finish(2)
run(INNER + ['select-pane', '-t', 'i.1'])
hold(2.5)

R, Lp = 1, 0
do(R, '# 1. Where: sdfiana025, a fresh clone of upstream (not a fork)')
do(R, "hostname; date '+%F %T %Z'; g++ --version | head -1")
do(R, 'bash clone.sh upstream ' + SHA, timeout=300, hold_s=2.5)
do(R, "cd upstream; git remote get-url origin; git log -1 --format='%H%n%cd'", expect=SHA, hold_s=7)

focus(Lp)
do(Lp, '# 2. The function. hl adds the colours')
do(Lp, 'cd upstream/xtcdata/xtcdata/xtc', hold_s=1.5)
do(Lp, "nl -ba -w3 -s'  ' Damage.hh | sed -n 12,43p | hl", hold_s=16)

focus(R)
do(R, '# 3. UserDefined = 12; the mask keeps bits 0-11. Line 38 adds 0.', hold_s=5)
do(R, '#    Seven places in the DRP flag a bad event with it:', hold_s=2.5)
do(R, "grep -n 'increase(.*UserDefined)' psdaq/drp/*.cc | sed -E 's/:[[:space:]]+/: /'", hold_s=10)
do(R, 'clear', hold_s=1.0)
do(R, '# 4. The reproduction. Damage.hh is header-only.')
do(R, 'cat ../repro.cc', hold_s=12)
do(R, 'g++ -I xtcdata ../repro.cc -o repro && ./repro; echo "exit $?"', expect=r'^exit \d+', hold_s=10)
do(R, "git rev-parse --short HEAD; date '+%F %T %Z'", hold_s=6)
finish(0)
