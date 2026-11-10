#!/bin/bash
# base (wt-base-t4, b6f370d9f) vs head (wt-final) with no simulated device: hpsBldServer, hpsBldCopy, bldcas, pyhpsbld
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2
L=$R/work/tail3
NS=""
if unshare -rn true 2>/dev/null; then NS="unshare -rn"; fi
echo "network namespace for the hardware command: ${NS:-none (then -a 127.0.0.1 only)}"
for wt in wt-base-t4 wt-final; do
 (
  W=$R/$wt; source $L/denv.sh; cd /tmp
  O=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/proof15/hw/basehead/$wt; rm -rf $O; mkdir -p $O
  echo "== $wt $(git -C $W rev-parse --short HEAD) tracked-dirty=$(git -C $W status --porcelain --untracked-files=no | wc -l) hpsBldServer=$(which hpsBldServer)"
  echo "\$ hpsBldServer -h"; hpsBldServer -h > $O/usage.txt 2>&1; echo "EXIT=$?"; cat $O/usage.txt
  if [ -n "$NS" ]; then
    echo "\$ $NS strace hpsBldServer -i lo -n DAQ:LAB2:HPSEX -p 0x1e0 -a 10.0.3.105   (lab3-bld.cnf:63 with -i lo; no network in the namespace)"
    timeout -k 5 30 $NS bash -c "PATH=/usr/sbin:/sbin:\$PATH ip link set lo up && ip -br addr show lo | tr -s ' ' > $O/netns.txt && ip route > $O/route.txt; exec strace -f -qq -e trace=connect,sendto,sendmsg,bind -o $O/hw.strace hpsBldServer -i lo -n DAQ:LAB2:HPSEX -p 0x1e0 -a 10.0.3.105" > $O/hw.out 2>&1; echo "EXIT=$?"
    echo "namespace: $(cat $O/netns.txt) routes: [$(cat $O/route.txt | tr '\n' ';')]"
    grep -v "Packets    0.00" $O/hw.out | grep -iv "warning" | tail -4 | cut -c1-200
    echo "connects: $(grep -o 'connect([0-9]*, {sa_family=AF_INET, sin_port=htons([0-9]*), sin_addr=inet_addr("[0-9.]*")' $O/hw.strace | sed 's/.*htons(\([0-9]*\)), sin_addr=inet_addr("\([0-9.]*\)").*/\2:\1/' | sort | uniq -c | tr '\n' ' ')"
    echo "sends: $(grep -E 'sendto|sendmsg' $O/hw.strace | grep -o 'sin_port=htons([0-9]*), sin_addr=inet_addr("[0-9.]*")' | sed 's/sin_port=htons(\([0-9]*\)), sin_addr=inet_addr("\([0-9.]*\)")/\2:\1/' | sort | uniq -c | tr '\n' ' ') results: $(grep -E 'sendto|sendmsg' $O/hw.strace | grep -o '= -1 [A-Z]*\|= [0-9]*$' | sort | uniq -c | tr '\n' ' ')"
  fi
  echo "\$ strace hpsBldServer -i lo -n DAQ:LAB2:HPSEX -p 0x1e0 -a 127.0.0.1   (loopback, nothing listens on 8193/8198)"
  timeout -k 5 30 strace -f -qq -e trace=connect,sendto,sendmsg,bind -o $O/lo.strace hpsBldServer -i lo -n DAQ:LAB2:HPSEX -p 0x1e0 -a 127.0.0.1 > $O/lo.out 2>&1; echo "EXIT=$?"
  grep -v "Packets    0.00" $O/lo.out | grep -iv "warning" | tail -3 | cut -c1-200
  echo "connects: $(grep -o 'connect([0-9]*, {sa_family=AF_INET, sin_port=htons([0-9]*), sin_addr=inet_addr("[0-9.]*")' $O/lo.strace | sed 's/.*htons(\([0-9]*\)), sin_addr=inet_addr("\([0-9.]*\)").*/\2:\1/' | sort | uniq -c | tr '\n' ' ')"
  echo "sends: $(grep -E 'sendto|sendmsg' $O/lo.strace | grep -o 'sin_port=htons([0-9]*), sin_addr=inet_addr("[0-9.]*")' | sed 's/sin_port=htons(\([0-9]*\)), sin_addr=inet_addr("\([0-9.]*\)")/\2:\1/' | sort | uniq -c | tr '\n' ' ')"
  echo "\$ hpsBldCopy"; hpsBldCopy > $O/copy.txt 2>&1; echo "EXIT=$?"; cat $O/copy.txt
  echo "\$ python: pyhpsbld.hps_init's signature"
  python -c "import inspect, psdaq.pyhpsbld.pyhpsbld as m; print(inspect.signature(m.hps_init))" 2>&1 | grep -v "^Rogue" | tail -1
  echo "\$ bldcas -P DAQ:LAB2 HPSEX (lab3-bld.cnf:59 with bld_cp=[]), own PVA ports; its table and its PVs' values"
  EPICS_PVAS_SERVER_PORT=31498 EPICS_PVAS_BROADCAST_PORT=31499 timeout -k 5 12 bldcas -P DAQ:LAB2 HPSEX > $O/bldcas.out 2>&1 &
  sleep 6
  python -c "
from psdaq.sim import gui_witness as g
c=g.pva_context(31499); print({n: int(c.get(n, timeout=3)) for n in ('DAQ:LAB2:HPSEX:ADDR','DAQ:LAB2:HPSEX:PORT')})" 2>&1 | tail -1
  wait; grep -v "^\s*$" $O/bldcas.out | head -6
 ) 2>&1
done
for f in usage.txt copy.txt bldcas.out; do echo "diff $f: $(diff /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/proof15/hw/basehead/wt-base-t4/$f /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/proof15/hw/basehead/wt-final/$f > /dev/null && echo same || diff /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/proof15/hw/basehead/wt-base-t4/$f /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/proof15/hw/basehead/wt-final/$f | tr '\n' '|')"; done
date -Is
