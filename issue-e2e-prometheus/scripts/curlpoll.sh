#!/bin/bash
# independent read-back: every 0.3 s, curl each exporter listed in $1/prom/*.yaml and print its TEB_WrtCt line
while :; do
  for y in "$1"/prom/*.yaml; do
    p=$(grep -o ":[0-9]*'" "$y" | tr -d ":'")
    v=$(curl -s -m 1 "http://127.0.0.1:$p/metrics" | grep '^TEB_WrtCt')
    [ -n "$v" ] && echo "$(date -u +%T.%3N) curl 127.0.0.1:$p $v"
  done
  sleep 0.3
done
