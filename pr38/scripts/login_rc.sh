# rc for the recorded login-host shell: ssh -t sdfiana025 bash --rcfile .../p38b/login_rc.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export Q=$R/logs/covbind/p38b EV=$R/logs/covbind/p38b/evidence
export S="srun --jobid=43843200 --overlap --ntasks=1 --cpus-per-task=16 --mem=32G"
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
cd $R/wt-covbind
