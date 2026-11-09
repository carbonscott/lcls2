#!/bin/bash
# daq_sim coverage over this proof's evidence dir, at the checkout's HEAD (one Slurm step)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b/env.sh
hdr
daq_sim coverage --evidence $Q/evidence; echo COVERAGE_EXIT=$?
