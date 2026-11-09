#!/bin/bash
# The epixhr2x2 DRP under sim:// at the current build, as run: it aborts at startup when
# BEBDetector imports psdaq.configdb.epixhr2x2_config.
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/xpm/env.sh
echo "host=$(hostname) head=$(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l) date=$(date -Is) job=$SLURM_JOB_ID step=$SLURM_STEP_ID"
D=$(mktemp -d /tmp/xpm-epixhr2x2-XXXX)
echo "\$ drp -P tst -C 127.0.0.1 -D epixhr2x2 -d sim://127.0.0.1:31099 -l 0x1 -o $D -u epixhr2x2_0 -p 7"
timeout -k 2 40 drp -P tst -C 127.0.0.1 -D epixhr2x2 -d sim://127.0.0.1:31099 -l 0x1 -o $D -u epixhr2x2_0 -p 7 2>&1 | grep -v 'Inadequate RTPRIO\|^  File "<frozen' | tail -14
echo "rc=${PIPESTATUS[0]}"
rm -rf $D
