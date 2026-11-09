#!/usr/bin/env python3
"""Record a terminal session: a detached tmux pane wrapped in asciinema, driven by a step file.

usage: recdrive.py NAME STEPS.json [--cols 140 --rows 40]

STEPS.json: a list of steps, each {"send": "<text>", "expect": "<regex>"?, "timeout": <s>?, "prompt": true?}
  send     text typed into the pane, followed by Enter
  expect   regex that must appear in the pane (scrollback included) before the step is done
  prompt   wait for a fresh shell prompt (default true when no expect is given)
  timeout  seconds (default 120); on timeout the recording stops with exit 2
Outputs in rec/NAME/: session.cast (asciinema), frames.jsonl (pane snapshots with times), driver.log
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT = re.compile(r'(\$|#)\s*$')


TMUX = ['tmux', '-L', 'recsock', '-f', os.path.join(HERE, 'rec.tmux.conf')]


def sh(*a, check=True):
    if a and a[0] == 'tmux':
        a = tuple(TMUX) + tuple(a[1:])
    return subprocess.run(a, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout


def main():
    name, steps_file = sys.argv[1], sys.argv[2]
    cols = int(sys.argv[sys.argv.index('--cols') + 1]) if '--cols' in sys.argv else 140
    rows = int(sys.argv[sys.argv.index('--rows') + 1]) if '--rows' in sys.argv else 40
    steps = json.load(open(steps_file))
    out = os.path.join(HERE, 'rec', name)
    os.makedirs(out, exist_ok=True)
    sess = 'rec-' + name
    sh('tmux', 'kill-session', '-t', sess, check=False)
    rc = os.path.join(HERE, 'local_rc.sh')
    cast = os.path.join(out, 'session.cast')
    sh('tmux', 'new-session', '-d', '-s', sess, '-x', str(cols), '-y', str(rows),
       f'asciinema rec -q --overwrite --cols {cols} --rows {rows} -c "bash --rcfile {rc} -i" {cast}')
    log = open(os.path.join(out, 'driver.log'), 'w')
    frames = open(os.path.join(out, 'frames.jsonl'), 'w')
    last = [None]

    def snap():
        txt = sh('tmux', 'capture-pane', '-p', '-e', '-t', sess, check=False)
        if txt and txt != last[0]:
            frames.write(json.dumps({'t': time.time(), 'screen': txt}) + '\n')
            frames.flush()
            last[0] = txt
        return txt

    def history():
        return sh('tmux', 'capture-pane', '-p', '-S', '-50000', '-t', sess, check=False)

    def wait(pred, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            snap()
            if pred():
                return True
            time.sleep(0.25)
        return False

    def at_prompt():
        lines = [l for l in sh('tmux', 'capture-pane', '-p', '-t', sess, check=False).split('\n') if l.strip()]
        return bool(lines) and bool(PROMPT.search(lines[-1]))

    status = 0
    wait(at_prompt, 30)
    for i, st in enumerate(steps):
        if status and not st.get('always'):
            log.write(f'{time.strftime("%H:%M:%S")} step {i} skipped after a failure: {st["send"][:100]}\n')
            continue
        before = len(history())
        t0 = time.time()
        text = st['send']
        k = 0
        while k < len(text):                       # type it, so the recording shows the command being entered
            j = min(k + 6, len(text))
            while j < len(text) and text[j - 1] == ';':
                j += 1                             # tmux reads an argument ending in ';' as a command separator
            chunk = text[k:j]
            if chunk.endswith(';'):
                chunk = chunk[:-1] + '\\;'
            sh('tmux', 'send-keys', '-t', sess, '-l', '--', chunk)
            k = j
            snap()
            time.sleep(0.03)
        sh('tmux', 'send-keys', '-t', sess, 'Enter')
        timeout = st.get('timeout', 120)
        exp = re.compile(st['expect'], re.M) if st.get('expect') else None
        want_prompt = st.get('prompt', True)
        time.sleep(0.6)

        def done():
            h = history()
            if exp and not exp.search(h[max(0, before - 200):]):
                return False
            return at_prompt() if want_prompt else True

        ok = wait(done, timeout)
        if ok and st.get('fail') and re.search(st['fail'], history()[max(0, before - 200):], re.M):
            ok = False
        log.write(f'{time.strftime("%H:%M:%S")} step {i} {"ok" if ok else "TIMEOUT"} {time.time()-t0:.1f}s: {st["send"][:100]}\n')
        log.flush()
        if not ok:
            status = 2
    # let the final screen settle, then end the session
    wait(lambda: False, 2)
    if status:                                     # leave no remote shell (and its Slurm step) behind
        for _ in range(3):
            sh('tmux', 'send-keys', '-t', sess, 'C-c', check=False); time.sleep(1)
            sh('tmux', 'send-keys', '-t', sess, '-l', '--', 'exit', check=False)
            sh('tmux', 'send-keys', '-t', sess, 'Enter', check=False); time.sleep(3)
    sh('tmux', 'kill-session', '-t', sess, check=False)
    with open(os.path.join(out, 'history.txt'), 'w') as f:
        f.write(last[0] or '')
    log.write(f'end status {status}\n')
    print(open(os.path.join(out, 'driver.log')).read())
    sys.exit(status)


main()
