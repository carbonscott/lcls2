# Upstream-only environment: the conda env upstream's setup_env_daq.sh activates (lines 15-20), and an upstream
# checkout's psdaq on PYTHONPATH (dtica, pvedit, dticas and PVAServer are pure Python). No fork code.
HERE=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/dtica-upstream
unset LD_LIBRARY_PATH PYTHONPATH
source /sdf/group/lcls/ds/ana/sw/conda2-v6/inst/etc/profile.d/conda.sh
export CONDA_ENVS_DIRS=/sdf/group/lcls/ds/ana/sw/conda2/inst/envs
conda activate daq_20250402_r9
export PYTHONPATH=$HERE/lcls2/psdaq
export QT_QPA_PLATFORM=offscreen
# PVA on loopback only, on private ports: $1 = server port (search port = $1 + 1)
pva_env() {
  export EPICS_PVAS_INTF_ADDR_LIST=127.0.0.1 EPICS_PVAS_SERVER_PORT=$1 EPICS_PVAS_BROADCAST_PORT=$(($1 + 1))
  export EPICS_PVAS_AUTO_BEACON_ADDR_LIST=NO EPICS_PVAS_BEACON_ADDR_LIST=127.0.0.1
  export EPICS_PVA_ADDR_LIST=127.0.0.1 EPICS_PVA_AUTO_ADDR_LIST=NO EPICS_PVA_BROADCAST_PORT=$(($1 + 1))
  export EPICS_PVA_SERVER_PORT=$1
}
