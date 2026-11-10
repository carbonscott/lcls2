#!/bin/bash
# commit.sh: fix15b's three commits on pr/final in wt-final (author as the branch's last commit; CHANGELOG versions v1..v3)
set -e
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/wt-final
F=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/fix15b
test "$(git rev-parse HEAD)" = b14885af349db9d58d24f6a5670e925286b3737b
test "$(git branch --show-current)" = pr/final
AN="$(git log -1 --format=%an)"; AE="$(git log -1 --format=%ae)"
G() { git -c user.name="$AN" -c user.email="$AE" "$@"; }
cp $F/CHANGELOG.v1.md CHANGELOG.md
git add CHANGELOG.md psdaq/psdaq/sim/daq_sim.py psdaq/psdaq/sim/feature.py psdaq/psdaq/tests/test_sim_features.py
G commit -q -F $F/msg1.txt
cp $F/CHANGELOG.v2.md CHANGELOG.md
git add CHANGELOG.md psdaq/psdaq/sim/simsls.py psdaq/psdaq/tests/test_sim_sls.py
G commit -q -F $F/msg2.txt
cp $F/CHANGELOG.v3.md CHANGELOG.md
git add CHANGELOG.md psdaq/psdaq/webgui/README.md
G commit -q -F $F/msg3.txt
git status --short | head
git log --format='%H %an <%ae> %s' b14885af3..HEAD
git diff b14885af3 HEAD --stat
