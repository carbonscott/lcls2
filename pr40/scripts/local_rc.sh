# rc for the local (exe.dev VM) shell inside a recording
export PS1='\[\e[1;36m\]exedev@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
cd /home/exedev/projects/lcls2/redo
alias ssh='ssh -F /home/exedev/projects/lcls2/redo/ssh_config'
unset LC_ALL LC_CTYPE
export LANG=C.UTF-8
export R=/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
