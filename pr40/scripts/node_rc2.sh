# rc for the recorded node shell: srun --pty flock -w 5400 /tmp/agentify-daq-milan120.lock bash --rcfile /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof40/node_rc2.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
source /sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/logs/proof40/penv.sh
export P=$Q/run2 WD=$Q/run2/dsw
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
cd $R
