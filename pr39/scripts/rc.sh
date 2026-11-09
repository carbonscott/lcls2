# rc for the recorded sdfiana025 shell: ssh -t sdfiana025 bash --rcfile $R/logs/proof39/rc.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
export R=/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export B=$R/logs/proof39
export S="srun --jobid=43839059 --overlap --ntasks=1 --cpus-per-task=16 --mem=32G"
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
cd $R/wt-types2
