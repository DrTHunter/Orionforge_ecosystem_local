#!/usr/bin/env bash
# check.sh — one-shot liveness check for any daemon that writes a pidfile.
# A pidfile is TESTIMONY. The kernel is EVIDENCE. A pidfile can be stale, recycled
# or hand-written; the process table cannot. This never loops: a checker that can
# die quietly is a second corpse. Silent on pass, so it composes with `&&`.
#
# Usage: check.sh <pidfile> <expected-name-substring> [max-age-seconds]
# Exit:  0 ALIVE · 1 DEAD · 2 MISMATCH (alive but wrong process, or loop stalled) · 3 usage
#
# Example: check.sh ~/kit/heartbeat/.daemon.pid bash 180
set -u
PIDFILE="${1:-}"; EXPECT="${2:-}"; MAXAGE="${3:-180}"

if [[ -z "$PIDFILE" || -z "$EXPECT" ]]; then
  echo "usage: check.sh <pidfile> <expected-name-substring> [max-age-seconds]" >&2
  exit 3
fi
if [[ ! -f "$PIDFILE" ]]; then
  echo "DEAD  $PIDFILE — no pidfile at all (never started, or cleaned up)"
  exit 1
fi
PID="$(tr -d '[:space:]' < "$PIDFILE")"
if [[ ! "$PID" =~ ^[0-9]+$ ]]; then
  echo "DEAD  $PIDFILE — pidfile holds '$PID', not a pid"
  exit 1
fi

# Ask the kernel, not the file.
COMM="$(ps -p "$PID" -o comm= 2>/dev/null | tr -d '[:space:]')"
if [[ -z "$COMM" ]]; then
  echo "DEAD  $PIDFILE — pid $PID is not running (the pidfile is a tombstone)"
  exit 1
fi
# Pids recycle: a live pid is not proof it is OUR process.
if [[ "$COMM" != *"$EXPECT"* ]]; then
  echo "MISMATCH  $PIDFILE — pid $PID is '$COMM', not '*$EXPECT*' (recycled pid?)"
  exit 2
fi
# Alive but not beating is a zombie in spirit (only if the pidfile has a sibling .beat stamp).
BEAT="${PIDFILE%.pid}.beat"
if [[ -f "$BEAT" ]]; then
  AGE=$(( $(date +%s) - $(stat -c %Y "$BEAT") ))
  if (( AGE > MAXAGE )); then
    echo "MISMATCH  $PIDFILE — pid $PID alive as '$COMM' but last beat ${AGE}s ago (> ${MAXAGE}s): loop stalled"
    exit 2
  fi
fi
exit 0
