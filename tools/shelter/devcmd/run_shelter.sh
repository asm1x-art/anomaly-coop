#!/bin/bash
# run.sh <1|2> <script.lua>: send a dev command to game 1 or 2 and wait for its [devcmd] result
D="$(cd "$(dirname "$0")" && pwd)"
dir=/h/anomaly-shelter/appdata
log=$dir/logs/xray_artem.log
nonce="n$RANDOM$RANDOM"
{ echo "local r = (function()"; cat "$D/$2"; echo; echo "end)()"; echo "return \"$nonce \" .. tostring(r)"; } > $dir/coop_devcmd.tmp && mv -f $dir/coop_devcmd.tmp $dir/coop_devcmd.lua
for i in $(seq 1 30); do
  sleep 1
  if grep -aq "$nonce" $log; then grep -a "$nonce" $log | tail -1; exit 0; fi
  if grep -aq "FATAL ERROR" $log; then echo "GAME $1 CRASHED"; grep -a "LUA error\|SCRIPT ERROR\|Expression" $log | tail -3; exit 1; fi
done
echo "no result from game $1"
