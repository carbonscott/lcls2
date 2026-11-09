#!/bin/bash
# nocuda.sh <base worktree> <head worktree>: their no-CUDA builds (nvcc not found, so no drpGpu) compared:
# the targets ninja builds and the commands it runs for them, with each worktree's path replaced by <wt>
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh $2
O=${P:-$L/rec}
for W in $1 $2; do
  B=$R/$W/builddir
  echo "$W: $(git -C $R/$W rev-parse --short HEAD), $(grep -m1 '^Program nvcc found' $B/meson-logs/meson-log.txt), drpGpu targets: $(ninja -C $B -t targets all | grep -c drpGpu)"
  ninja -C $B -t targets all | sed "s#$R/$W#<wt>#g; s#/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g" | sort > $O/targets-$W.txt
  ninja -C $B -t commands | sed "s#$R/$W#<wt>#g; s#/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/$W#<wt>#g" | sort > $O/commands-$W.txt
  echo "  $(wc -l < $O/targets-$W.txt) targets, $(wc -l < $O/commands-$W.txt) build commands"
done
diff $O/targets-$1.txt $O/targets-$2.txt > /dev/null; echo "TARGETS_DIFF_EXIT=$?"
diff $O/commands-$1.txt $O/commands-$2.txt > /dev/null; echo "COMMANDS_DIFF_EXIT=$?"
