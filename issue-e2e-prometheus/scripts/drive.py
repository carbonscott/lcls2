#!/usr/bin/env python3
"""W13 recording driver (runs on sdfiana025 under nohup): types steps into a pane of a private tmux
server (tmux -L w13) whose pane runs `script` around the recorded shell, and snapshots the pane.

usage: drive.py RUNDIR STEPS.json SESSION
STEPS.json: [{"chapter": "label"?, "send": "text", "timeout": s?, "pause": s?}, ...]
  each step types `send` + Enter and waits for the next shell prompt (a new prompt line in the
  pane's history); "pause" waits that long afterwards (for the viewer).
Writes RUNDIR/frames.jsonl ({"t": epoch, "screen": pane with ANSI}), RUNDIR/chapters.jsonl
({"t": epoch, "utc": iso, "label": ...}) and RUNDIR/driver.log.
"""
import datetime, json, os, re, subprocess, sys, time

PROMPT = re.compile(r'^\d\d:\d\d:\d\dZ \S+@\S+:\S+[#$]( |$)')


def tmux(*a):
    return subprocess.run(('tmux', '-L', 'w13') + a, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True).stdout


def main():
    run, steps, sess = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]
    frames = open(os.path.join(run, 'frames.jsonl'), 'a')
    chap = open(os.path.join(run, 'chapters.jsonl'), 'a')
    log = open(os.path.join(run, 'driver.log'), 'a')
    last = [None]

    def say(msg):
        log.write('%s %s\n' % (datetime.datetime.utcnow().strftime('%H:%M:%S.%f')[:12], msg))
        log.flush()

    def alive():
        return subprocess.run(['tmux', '-L', 'w13', 'has-session', '-t', sess],
                              stderr=subprocess.DEVNULL).returncode == 0

    def snap():
        s = tmux('capture-pane', '-p', '-e', '-t', sess)
        if s and s != last[0]:
            frames.write(json.dumps({'t': time.time(), 'screen': s}) + '\n')
            frames.flush()
            last[0] = s

    def prompts():
        h = tmux('capture-pane', '-p', '-S', '-50000', '-t', sess)
        lines = h.rstrip('\n').split('\n')
        n = sum(1 for l in lines if PROMPT.match(l))
        idle = bool(lines) and PROMPT.match(lines[-1]) is not None and lines[-1].rstrip().endswith(('#', '$'))
        return n, idle

    def wait_prompt(n0, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            snap()
            n, idle = prompts()
            if n > n0 and idle:
                return True
            if not alive():
                return False
            time.sleep(0.25)
        return False

    say('start; waiting for the first prompt')
    if not wait_prompt(0, 300):
        say('no first prompt: stop')
        return 2
    for i, st in enumerate(steps):
        n0, _ = prompts()
        if st.get('chapter'):
            now = time.time()
            chap.write(json.dumps({'t': now, 'utc': datetime.datetime.utcfromtimestamp(now).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                   'label': st['chapter']}) + '\n')
            chap.flush()
        say('step %d: %s' % (i, st['send'][:150]))
        tmux('send-keys', '-t', sess, '-l', '--', st['send'])
        time.sleep(0.3)
        tmux('send-keys', '-t', sess, 'Enter')
        if st['send'].strip() == 'exit':
            break
        if not wait_prompt(n0, st.get('timeout', 600)):
            say('step %d: no prompt after %s s: stop' % (i, st.get('timeout', 600)))
            return 2
        t1 = time.time()
        while time.time() - t1 < st.get('pause', 1.5):
            snap()
            time.sleep(0.25)
    t0 = time.time()
    while alive() and time.time() - t0 < 30:
        snap()
        time.sleep(0.25)
    say('done')
    return 0


if __name__ == '__main__':
    sys.exit(main())
