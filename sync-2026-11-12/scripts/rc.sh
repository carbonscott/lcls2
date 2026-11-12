# rc for the recorded shell in the Slurm step on sdfada010 (sync/upstream-2026-11-12 proof)
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export PS1='\[\e[1;32m\]cwang31@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
export XDG_CACHE_HOME=$R/cache/xdg UV_CACHE_DIR=$R/cache/uv PYTHONDONTWRITEBYTECODE=1
