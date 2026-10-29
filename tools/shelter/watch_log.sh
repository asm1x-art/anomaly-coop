#!/bin/bash
# watch_log.sh <pid>: watch the shelter test game while the user plays: every 30 s ask it to flush its log (a no-op dev
# command, run only once in a level), print new error lines (not the known placeable_items_trade one), say when the
# process is gone
LOG=/h/anomaly-shelter/appdata/logs/xray_artem.log
DIR=/h/anomaly-shelter/appdata
PID=$1
last=0
while true; do
	if ! tasklist //FI "PID eq $PID" //FO CSV 2>/dev/null | grep -q "\"$PID\""; then
		echo "game process $PID is gone"
		grep -a -E "\[error\](Expression|Function|Description|Arguments)" $LOG | tail -4 | iconv -f cp1251 -t utf-8
		exit 0
	fi
	printf 'return "flush"\n' > $DIR/coop_devcmd.tmp && mv -f $DIR/coop_devcmd.tmp $DIR/coop_devcmd.lua
	sleep 30
	n=$(wc -l < $LOG)
	[ "$n" -lt "$last" ] && last=0
	if [ "$n" -gt "$last" ]; then
		sed -n "$((last + 1)),${n}p" $LOG | grep -a -E "SCRIPT ERROR|LUA error|FATAL|\[error\]|! \[shelter\]|Runtime Error|stack trace" \
			| grep -av "placeable_items_trade" | head -6 | iconv -f cp1251 -t utf-8 -c
		last=$n
	fi
done
