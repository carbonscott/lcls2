#!/bin/bash
# loss.sh TAG DRP N: N short runs of 'daq_sim matrix --only types --drp DRP --types jungfrau' (the matrix's jungfrau
# type cycle) at wt-final's install on this node, under its DAQ lock; beside each run a sampler reads /proc/net/udp
# every 0.2 s (this user's 127.0.0.1 sockets: rx queue and drops).  Per run: simsls' frames and packets sent, the
# DRP data socket's drops (packets the kernel dropped at its full receive buffer), MemPoolSim's incomplete-frame
# lines, DRP_Damage, the type's per-event result, and the node's Udp RcvbufErrors delta (all UDP sockets on the node)
TAG=$1; DRP=$2; N=$3
source /sdf/data/lcls/ds/prj/prjcwang31/scratch/main/agentify-lcls2/work/fix15b/env.sh
hdr "loss $TAG: drp $DRP jungfrau x$N, lock $LOCK, rmem_max $(cat /proc/sys/net/core/rmem_max), simsls $(md5sum < install/lib/python3.9/site-packages/psdaq/sim/simsls.py | cut -c1-8)"
U=$(id -u)
rbe() { awk '/^Udp:/{n++; if (n==2) print $6}' /proc/net/snmp; }
for k in $(seq 1 $N); do
  WD=$W/loss-$TAG-$k; S=$WD.udp
  ( while :; do awk -v u=$U -v t=$(date +%s.%N) 'NR>1 && $8==u && $2 ~ /^0100007F:/ {print t, $2, $5, $10, $13}' /proc/net/udp; sleep 0.2; done ) > $S 2>/dev/null &
  sp=$!
  r0=$(rbe); t0=$(date +%s)
  daq_sim matrix -w $WD --only types --drp $DRP --types jungfrau --lock $LOCK --lock-timeout 3600 > $WD.log 2>&1; rc=$?
  r1=$(rbe); kill $sp; wait $sp 2>/dev/null
  dl=$(grep -rh "its frames arrive on 127.0.0.1:" $WD/ 2>/dev/null | head -1 | sed -E 's/.*arrive on 127.0.0.1:([0-9]+).*/\1/')
  ph=$(printf '0100007F:%04X' ${dl:-0})
  drops=$(awk -v p=$ph '$2==p {if ($5+0>m) m=$5+0} END {print m+0}' $S)
  maxq=$(awk -v p=$ph '$2==p {split($3,a,":"); q=strtonum("0x" a[2]); if (q>m) m=q} END {print m+0}' $S)
  sls=$(grep -rh "exiting: status" $WD/ 2>/dev/null | tail -1 | grep -oE "'frames': [0-9]+, 'packets': [0-9]+")
  inc=$(grep -rh "MemPoolSim: module .* sent .* of 128 packets" $WD/ 2>/dev/null | wc -l)
  dmg=$(grep -h "counts after Disable" $WD.log | tail -1 | grep -oE "'DRP_Damage': [0-9]+")
  echo "RUN $TAG-$k exit $rc in $(( $(date +%s) - t0 )) s: data port ${dl:-?}; simsls sent {$sls}; receiver drops $drops (max queue $maxq B); incomplete-frame lines $inc; $dmg; node RcvbufErrors +$((r1-r0))"
  grep -E '^TYPE ' $WD.log | cut -c1-200
done
hdr "loss $TAG done"
