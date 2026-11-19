#!/bin/bash
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/dtica-upstream/env.sh > /dev/null 2>&1
pva_env 47470; cd $HERE; python min_gc.py
