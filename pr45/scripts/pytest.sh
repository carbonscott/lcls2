#!/bin/bash
# pytest.sh: the sim unit tests (psdaq/psdaq/tests/test_sim*.py) at this checkout, under the node's DAQ lock
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof45/env.sh wt-gpu
hdr pytest
T=$(ls psdaq/psdaq/tests/test_sim*.py)
echo "$(echo $T | wc -w) files: $(echo $T | xargs -n1 basename | sed 's/\.py$//' | tr '\n' ' ')" | c
( flock -w 5400 9 || { echo "node lock not taken"; exit 3; }
  timeout -k 5 1500 python -m pytest -q -p no:cacheprovider $T > ${P:-$L/rec}/pytest.log 2>&1; echo "PYTEST_EXIT=$?"
) 9>$LOCK
grep -E '^[0-9]+ (passed|failed)|passed|failed|error' ${P:-$L/rec}/pytest.log | grep -v Warning | tail -2 | c
