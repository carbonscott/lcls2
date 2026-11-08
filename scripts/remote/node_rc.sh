# rc for the recorded node shell: srun --pty bash --rcfile $R/redo/node_rc.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/redo/env.sh
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
cd $R/redo
