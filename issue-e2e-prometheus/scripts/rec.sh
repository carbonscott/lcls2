#!/bin/bash
# W13: start the one-take recording (run on sdfiana025): a private tmux server (-L w13) whose pane runs
# `script` around `srun --pty unshare -rn bash -i` on the roma node; drive.py types steps.json into it.
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/sim-main-sync; B=$R/w/w13/bin
RID=$1; RUN=$R/runs/$RID; mkdir -p $RUN
cp $B/rc.sh $B/steps.json $B/rec.tmux.conf $RUN/
unset TMUX; export LANG=C.UTF-8 TZ=UTC
tmux -L w13 -f $RUN/rec.tmux.conf new-session -d -s rec -x 160 -y 48 \
  "date +%s.%N > $RUN/chapters.jsonl.start; script -q -f --timing=$RUN/timing $RUN/typescript -c 'srun --jobid=45757390 --overlap -w sdfrome046 --ntasks=1 --cpus-per-task=64 --mem=128G --pty unshare -rn bash --rcfile $RUN/rc.sh -i'; echo SCRIPT_EXIT=\$? > $RUN/script.exit; sleep 3"
nohup python3 $B/drive.py $RUN $RUN/steps.json rec > $RUN/drive.out 2>&1 &
echo "rec started $RID $(date -u +%FT%TZ) driver pid $!"
