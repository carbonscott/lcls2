# rc for the second recorded sdfiana025 shell: ssh -t sdfiana025 bash --rcfile $R/work/proof15/rc2.sh -i (rc.sh with short() unbuffered)
[ -f ~/.bashrc ] && source ~/.bashrc >/dev/null 2>&1
export XDG_CACHE_HOME=/sdf/scratch/users/c/cwang31/.cache-agentify UV_CACHE_DIR=/sdf/scratch/users/c/cwang31/.cache-agentify
export R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
export Q=$R/work/proof15
export S="srun --jobid=44000948 --overlap -w sdfmilan023 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G"
export S2="srun --jobid=44000948 --overlap -w sdfmilan082 -N 1 --ntasks=1 --cpus-per-task=16 --mem=32G"
# the lines of the matrix's output shown in the pane (the whole output is tee'd to $Q/mx-<tag>.log)
export MXF='^=== matrix|MATRIX:|matrix: (types|GPU types|types on)|matrix: ---- |matrix: lock .* held|TYPE |PROGRAMS |FEATURE [a-e]:|FEATURE [a-e] (PASS|FAIL)|coverage\| [0-9]+ rows|^==== MATRIX|^(types \(|programs:|features:|coverage:|assertions:)|^  (PASS|FAIL)|^FAILED|^summary JSON|^whole|^MATRIX (PASS|FAIL)|^MATRIX_EXIT'
short() { sed -u -E "s# run /[^ ]+##; s#$R#\$R#g; s#/sdf/scratch/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2#\$R#g; s/^(.{138}).*/\1/"; }   # sed -u: cut buffers its output even on a terminal
export PS1='\[\e[1;32m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\W\[\e[0m\]\$ '
export TERM=xterm-256color
cd $R/wt-final
