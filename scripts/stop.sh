#!/usr/bin/env bash
# scripts/start.sh 로 띄운 서버와 MediaMTX를 종료한다.
RUN="$HOME/.cache/yundo-ct-run"
for n in mediamtx server; do
  f="$RUN/$n.pid"
  if [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; then
    kill "$(cat "$f")" && echo "$n 종료 (PID $(cat "$f"))"
  else
    echo "$n: 실행 중이 아닙니다"
  fi
  rm -f "$f"
done
