#!/bin/bash
# code_capture.sh OUTDIR : the code behind sim-configdb-history, at the heads of carbonscott/lcls2 sim-main and
# slac-lcls/lcls2 master, plus a search of the fork's issues and pull requests. Writes OUTDIR/code-at-head.txt.
set -u
OUT=$1; mkdir -p "$OUT"
R=/sdf/data/lcls/ds/prj/prjcwang31/scratch/main/sim-issues/agents/h1/lcls2-sim
git -C $R fetch -q origin sim-main; git -C $R fetch -q --filter=blob:none upstream master
S=$(git -C $R rev-parse origin/sim-main); U=$(git -C $R rev-parse upstream/master)
{
echo "# host: $(hostname)"; echo "# date: $(date -u +%FT%TZ)"
echo "# commit: lcls2 $S (carbonscott/lcls2 sim-main) and $U (slac-lcls/lcls2 master)"
echo "# cmd: code_capture.sh $OUT"
echo
echo "\$ git ls-remote https://github.com/carbonscott/lcls2 HEAD refs/heads/sim-main"
git ls-remote https://github.com/carbonscott/lcls2 HEAD refs/heads/sim-main
echo
echo "\$ git show $S:psdaq/psdaq/sim/configdb_server.py | cat -n | sed -n '130,134p;211,222p'"
git -C $R show $S:psdaq/psdaq/sim/configdb_server.py | cat -n | sed -n '130,134p;211,222p'
echo
echo "\$ git show $S:psdaq/psdaq/configdb/typed_json.py | cat -n | sed -n '365,382p'"
git -C $R show $S:psdaq/psdaq/configdb/typed_json.py | cat -n | sed -n '365,382p'
echo
echo "\$ git diff $S $U -- psdaq/psdaq/configdb/typed_json.py psdaq/psdaq/configdb/mongoconfigdb.py | wc -l"
git -C $R diff $S $U -- psdaq/psdaq/configdb/typed_json.py psdaq/psdaq/configdb/mongoconfigdb.py | wc -l
echo
echo "\$ git show $U:psdaq/psdaq/configdb/mongoconfigdb.py | cat -n | sed -n '310,329p'    # the real service's get_history"
git -C $R show $U:psdaq/psdaq/configdb/mongoconfigdb.py | cat -n | sed -n '310,329p'
echo
for q in get_history configdb_server 'enum+configdb'; do
  echo "\$ curl -s 'https://api.github.com/search/issues?q=repo:carbonscott/lcls2+$q'"
  curl -s "https://api.github.com/search/issues?q=repo:carbonscott/lcls2+$q&per_page=50" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("total_count:", d.get("total_count"), d.get("message", ""))
for i in d.get("items", []):
    print("  #%s %s %s %s" % (i["number"], i["state"], "PR" if "pull_request" in i else "issue", i["title"][:110]))'
done
} > $OUT/code-at-head.txt 2>&1
cat $OUT/code-at-head.txt
