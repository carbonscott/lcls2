# rc for the recorded sdfiana025 shells of issue 47 (two tmux panes)
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export R=/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export L=$R/logs/issue47
export PS1='\[\e[1;32m\]\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
# hl: print stdin, colouring the three expressions the report is about
hl() { grep --color=always -E 'UserDefined += 12|ValueBitMask = 0x0fff|\(1 << v\) & ValueBitMask|$'; }
cd $L
