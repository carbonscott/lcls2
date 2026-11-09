# rc for the recorded node shell: srun --pty bash --rcfile $P/node_rc.sh -i
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
source /sdf/scratch/users/c/cwang31/guiproof/penv.sh
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
cd $R
