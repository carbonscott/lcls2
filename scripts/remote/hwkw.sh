#!/bin/bash
# A hardware-device DRP given a sim_* kwarg, at the base (25e6f4d) and at the PR head; each tree
# runs its own install with its own env. bogus_kw=1 is the control.
for T in $R/redo/wt-base $R/redo/wt-a2; do
  ( cd $T && source ./setup_env_daq.sh >/dev/null 2>&1
    echo "== $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-60)"
    for kw in sim_seed=1 bogus_kw=1; do
      timeout -k 2 15 ./install/bin/drp -P tst -C localhost -D fakecam -d /dev/datadev_0 -u hwcheck_0 -p 6 -k $kw > /tmp/hwkw.$$ 2>&1
      echo "   drp -d /dev/datadev_0 -k $kw -> exit $?: $(grep -iE 'unrecognized|kwarg|error opening' /tmp/hwkw.$$ | head -1)"
    done; rm -f /tmp/hwkw.$$ )
done
