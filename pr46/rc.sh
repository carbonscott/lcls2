# rc for the recorded sdfiana025 shell: ssh -t sdfiana025 bash --rcfile $R/logs/proof46/rc.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export R=/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export L=$R/logs/proof46
export ELAN_HOME=$R/cache/elan
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
ulimit -c 0
cd $R/wt-formal
