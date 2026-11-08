#!/bin/bash
# basemap.sh JUNIT WALK OUT(new): this checkout's check_parity, with the base's mapping (2d9593bc5, which maps
# the 5 CGWMainTabs / CGWMainTabUser rows) copied to OUT, on the same junit and walk.
JUNIT=$1; WALK=$2; OUT=$3; B=$R/wt-cov/psdaq/psdaq/webgui/parity
[ -n "$OUT" ] && [ ! -e "$OUT" ] || { echo "usage: basemap.sh JUNIT WALK OUT(new dir)"; exit 2; }
mkdir -p $OUT && cp -p $B/mapping.json $OUT/ && cp -rp $B/mapping.d $OUT/
echo "mapping: copy of $(git -C $R/wt-cov rev-parse --short HEAD):psdaq/psdaq/webgui/parity (mapping.json + mapping.d/)"
python -m psdaq.webgui.parity.check_parity --junit $JUNIT --walk $WALK --mapping $OUT/mapping.json > $OUT/parity.txt 2>&1; echo PARITY_BASEMAP_EXIT=$?
grep -E 'controls found|^walk|^Mapped but not built|^  CGWMainTab(s|User)\.|^RESULT' $OUT/parity.txt | cut -c1-230
