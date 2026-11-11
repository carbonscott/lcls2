#!/bin/bash
# A partial clone of slac-lcls/lcls2 at one commit, with only the directories the report cites.
#   usage: clone47.sh <dir> <sha>
set -e
git init -q "$1" && cd "$1"
git remote add origin https://github.com/slac-lcls/lcls2.git
git sparse-checkout set xtcdata/xtcdata/xtc psdaq/drp psana/psana/detector
git fetch -q --depth 1 --filter=blob:none origin "$2"
git checkout -q FETCH_HEAD
