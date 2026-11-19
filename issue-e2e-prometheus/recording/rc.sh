# W13 recorded shell: runs as `srun ... --pty unshare -rn bash --rcfile <this> -i` on the roma node
export TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8 GIT_PAGER=cat PAGER=cat
export ROOT=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/sim-main-sync
export XDG_CACHE_HOME=$ROOT/cache/xdg UV_CACHE_DIR=$ROOT/cache/uv PIP_CACHE_DIR=$ROOT/cache/pip
export PLAYWRIGHT_BROWSERS_PATH=$ROOT/cache/playwright
export BP=$ROOT/tools/webgui-venv/bin/python W13=$ROOT/w/w13 M=$ROOT/w/w13/m
ip link set lo up
cd $W13
PS1='\D{%H:%M:%S}Z \u@\h:\W\$ '
clear
