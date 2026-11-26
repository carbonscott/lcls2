#!/bin/bash
# excerpt.sh <git tree> <rev> <out> <path:from-to>...   numbered excerpts of files at one commit, with a provenance header
T=$1; R=$2; O=$3; shift 3
{
echo "# host: $(hostname)"
echo "# date: $(date -u +%FT%TZ)"
echo "# commit: $(git -C "$T" remote get-url ${REMOTE:-upstream} 2>/dev/null | sed 's|https://github.com/||') $(git -C "$T" rev-parse "$R")"
echo "# cmd: excerpt.sh <lcls2 clone> $R <out> $*"
for spec in "$@"; do
  p=${spec%%:*}; r=${spec#*:}; a=${r%-*}; b=${r#*-}
  echo; echo "== $p lines $a-$b at $(git -C "$T" rev-parse --short=12 "$R")"
  git -C "$T" show "$R:$p" | awk -v a=$a -v b=$b 'NR>=a && NR<=b {printf "%5d  %s\n", NR, $0}'
done
} > "$O"
