# rc for the recorded sdfiana025 shell: ssh -t sdfiana025 bash --rcfile $R/logs/proof45/rc.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export L=$R/logs/proof45
export S="srun --jobid=43970564 --overlap --ntasks=1 --cpus-per-task=12 --mem=48G"
export SG="$S --gres=gpu:l40s:1"
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
cd $R/wt-gpu
