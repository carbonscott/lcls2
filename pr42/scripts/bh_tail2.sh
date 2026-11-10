#!/bin/bash
# Base (pr/progtail a03cd961e, wt-base-t4) vs head (wt-final), with no simulated device selected (PSDAQ_SIM_TPR
# unset), the same commands, for the production files touched: psdaq/psdaq/app/lclsBldServer.cc,
# psdaq/psdaq/tpr/Client.cc, psdaq/psdaq/tpr/Client.hh. No packet is sent: with no /dev/tpra, tpr::Client throws
# before lclsBldServer's send loop; strace shows the socket calls (connect() on UDP sends nothing, joins nothing).
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/tail2/denv.sh
ulimit -c 0
echo "host=$(hostname) date=$(date -Is) /dev/tpra: $(ls /dev/tpra 2>&1) strace: $(which strace 2>&1)"
[ -e /dev/tpra ] && { echo "a TPR is present: stopping (this check needs none)"; exit 2; }
for wt in wt-base-t4 wt-final; do
  B=$R/$wt/install/bin; export LD_LIBRARY_PATH=$R/$wt/install/lib:$LD_LIBRARY_PATH
  cd $R/$wt
  echo "== $wt $(git rev-parse --short HEAD) dirty=$(git status --porcelain --untracked-files=no | wc -l)" \
       "lclsBldServer.cc $(git hash-object psdaq/psdaq/app/lclsBldServer.cc) Client.cc $(git hash-object psdaq/psdaq/tpr/Client.cc)" \
       "Client.hh $(git hash-object psdaq/psdaq/tpr/Client.hh)"
  echo "\$ ldd $wt/install/bin/lclsBldServer | grep libtpr"; ldd $B/lclsBldServer | grep libtpr
  echo "\$ env -u PSDAQ_SIM_TPR lclsBldServer -i enp1s0f1 -r 4     # lab3-bld.cnf:52 as it is"
  env -u PSDAQ_SIM_TPR timeout 30 $B/lclsBldServer -i enp1s0f1 -r 4 > /tmp/bh-$$-$wt-cnf.out 2>&1; echo "EXIT=$?"
  cat /tmp/bh-$$-$wt-cnf.out
  echo "\$ env -u PSDAQ_SIM_TPR strace -f -e trace=socket,bind,connect,setsockopt,sendto,sendmsg,openat lclsBldServer -i lo -r 4 -b ebeam"
  env -u PSDAQ_SIM_TPR timeout 30 strace -f -e trace=socket,bind,connect,setsockopt,sendto,sendmsg,openat \
      $B/lclsBldServer -i lo -r 4 -b ebeam > /tmp/bh-$$-$wt-b.out 2>&1; echo "EXIT=$?"
  grep -v 'openat(.*\(\.so\|/etc/\|/proc/\|/sys/\|locale\|gconv\)' /tmp/bh-$$-$wt-b.out | sed "s/^\[pid *[0-9]*\] //" | sed "s/^[0-9]* //" > /tmp/bh-$$-$wt-b.flt
  cat /tmp/bh-$$-$wt-b.flt
  echo "sendto/sendmsg calls: $(grep -c 'sendto\|sendmsg' /tmp/bh-$$-$wt-b.out)"
  echo "\$ env -u PSDAQ_SIM_TPR tprtrig -t a -c 0 -o 1 -d 2 -w 10 -p 5"
  env -u PSDAQ_SIM_TPR timeout 30 $B/tprtrig -t a -c 0 -o 1 -d 2 -w 10 -p 5 > /tmp/bh-$$-$wt-t.out 2>&1; echo "EXIT=$?"
  cat /tmp/bh-$$-$wt-t.out
done
echo "== diff base head: lab3-bld.cnf:52's command (only the usage lines of -a and the new -p may differ)"
diff /tmp/bh-$$-wt-base-t4-cnf.out /tmp/bh-$$-wt-final-cnf.out; echo "DIFF_EXIT=$?"
echo "== diff base head: the cnf's command with -b ebeam, socket calls and output (pids masked)"
diff <(sed 's/[0-9]\{4,\}/N/g' /tmp/bh-$$-wt-base-t4-b.flt) <(sed 's/[0-9]\{4,\}/N/g' /tmp/bh-$$-wt-final-b.flt); echo "DIFF_EXIT=$?"
echo "== diff base head: tprtrig"
diff /tmp/bh-$$-wt-base-t4-t.out /tmp/bh-$$-wt-final-t.out; echo "DIFF_EXIT=$?"
rm -f /tmp/bh-$$-*
date -Is
