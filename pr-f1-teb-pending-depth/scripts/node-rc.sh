# rc for the sdfada018 shell (srun --pty) of the PR-F1 recording
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-daq-hardening
cd $R/builds/cee776d3c
