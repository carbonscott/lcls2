#!/bin/bash
# mx.sh TAG: the full check at $WT's HEAD over $A,$B (job $JOB) and $G (job $GJOB); a fresh dir per TAG
TAG=$1; source $ROOT/simenv.sh $WT || exit 9
W=$P/work/mx-$TAG; EV=$W-ev
[ -e $W ] && { echo "$W exists: take a new TAG"; exit 2; }
mkdir -p $EV; export DAQ_SIM_EVIDENCE=$EV    # where each DAQ cycle writes its evidence record
echo "=== full check $TAG on $(hostname -s) job $SLURM_JOB_ID gpu $G job $GJOB $(date -u +%FT%TZ)"
daq_sim matrix -w $W --hosts $A,$B --locks /tmp/daq-$A.lock,/tmp/daq-$B.lock \
  --gpu-host $G --gpu-job $GJOB --gpu-gres gpu:l40s:1 --gpu-lock /tmp/daq-$G.lock \
  --ami-src $AMI --evidence $EV --lock-timeout 5400
echo "MATRIX_EXIT=$? $(date -u +%FT%TZ)"
