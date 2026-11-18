# rc for the recorded sdfiana025 shell: clock in the prompt
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export PS1='\[\e[0;33m\]\D{%H:%M:%S %Z}\[\e[0m\] \[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color LANG=C.UTF-8
cd /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/fnl-repro
clear
