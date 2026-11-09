#!/bin/bash
# the sim unit tests with the DAQ env, importing psdaq from the checkout's source (one Slurm step)
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/covbind/p38b/env.sh
export PYTHONPATH=$PWD/psdaq:$PYTHONPATH
hdr
python -c "import psdaq.sim.coverage as c; print('coverage from', c.__file__)"
T="psdaq/psdaq/tests/test_sim_coverage.py psdaq/psdaq/tests/test_sim_rogue_dev.py psdaq/psdaq/tests/test_sim_framer.py psdaq/psdaq/tests/test_sim_configdb_seed_store.py psdaq/psdaq/tests/test_sim_configdb.py psdaq/psdaq/tests/test_sim_lgbk.py psdaq/psdaq/tests/test_simxpm.py psdaq/psdaq/tests/test_sim_xpmdet_types.py"
timeout -k 5 900 python -m pytest -q -p no:cacheprovider $T 2>&1 | grep -v Warning
echo PYTEST_EXIT=${PIPESTATUS[0]}
