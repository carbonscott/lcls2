#!/usr/bin/env python3
"""Write redo/steps/pr46-term.json: the recorded proof of PR 46 (xtcdata/formal) at its head."""
import json, os, sys
RUN = sys.argv[1] if len(sys.argv) > 1 else 'take1'
steps = []
def s(send, expect=None, timeout=None):
    d = {'send': send}
    if expect: d['expect'] = expect
    if timeout: d['timeout'] = timeout
    steps.append(d)
W = f'$R/wt-proof46-{RUN}'
s('date -Is; hostname   # this machine: the exe.dev VM')
s('ssh -t sdfiana025 bash --rcfile $R/logs/proof46/rc.sh -i', expect=r'cwang31@sdfiana025', timeout=180)
s("hostname; date '+%F %T %Z'; cat /etc/redhat-release; gcc --version | head -1; valgrind --version")
s('# A clean checkout of the PR head in a new worktree: nothing built, nothing left over')
s(f"git fetch -q origin && git worktree add -q --detach {W} origin/formal/xtc2 && cd {W} && git rev-parse HEAD && git log -1 --format='%ad  %s' && echo \"local changes: $(git status --short | wc -l)\"", expect=r'local changes: \d+', timeout=300)
s("git diff --stat origin/sim-main HEAD | tail -1; echo 'files outside xtcdata/formal:'; git diff --name-only origin/sim-main HEAD | grep -v '^xtcdata/formal/'")
s('cd xtcdata/formal && . ./env.sh && (cd lean && lean --version) && ls')
s('# 1. Build the model. lake compiles every theorem; a proof that does not check stops the build')
s('(cd lean && time lake build 2>&1 | tail -4)', expect=r'real\s', timeout=2400)
s('# 2. Audit: the axioms each theorem rests on. Exit 0 only with no sorry and no unknown axiom')
s('./audit.sh | tail -9; echo "AUDIT_EXIT=${PIPESTATUS[0]}"', expect=r'AUDIT_EXIT=\d+', timeout=900)
s('# 2b. The audit must fail when it should: a copy with one false theorem "proved" by sorry')
s(f'bash $L/sorry.sh $PWD $R/work/proof46-sorry-{RUN} 2>&1 | tail -7', expect=r'AUDIT_EXIT=\d+', timeout=900)
s("# 3. Build the oracle: the tree's own xtcdata C++ sources, compiled here")
s('./difftest/build.sh 2>&1 | tail -4; ls -la difftest/build | grep oracle', timeout=900)
s('# 4. Each finding shown on the real C++ (and under valgrind), next to what the model says')
s('./difftest/findings.sh 2>&1 | cut -c1-150; echo "FINDINGS_EXIT=${PIPESTATUS[0]}"', expect=r'FINDINGS_EXIT=\d+', timeout=900)
s('# 5. Differential test: model against real code, 3 seeds, valgrind on the memory cases')
s('time python3 difftest/run.py --seeds 1 2 3 --n 80000 --valgrind; echo "RUN_EXIT=$?"', expect=r'RUN_EXIT=\d+', timeout=5400)
s('# 6. Mutation check: 14 deliberately wrong models. The test must catch every one')
s(f'python3 difftest/mutate.py --work $R/work/proof46-mut-{RUN} | tail -18; echo "MUT_EXIT=${{PIPESTATUS[0]}}"', expect=r'MUT_EXIT=\d+', timeout=10800)
s("git rev-parse HEAD; echo \"tracked files changed: $(git status --short --untracked-files=no | wc -l)\"; date '+%F %T %Z'")
os.makedirs('steps', exist_ok=True)
json.dump(steps, open('steps/pr46-term.json', 'w'), indent=1)
print(len(steps), 'steps')
