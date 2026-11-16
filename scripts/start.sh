#!/usr/bin/env bash
# 강의도구 서버 + MediaMTX를 백그라운드로 실행한다. 종료: scripts/stop.sh
# 환경변수(PORT, TEACHER_PASSWORD 등)는 그대로 서버에 전달된다. 기본 HOST=0.0.0.0(다른 PC 접속 허용).
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="$HOME/.cache/yundo-ct-run"   # PID·로그는 Google Drive 밖에 둔다
mkdir -p "$RUN"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
if alive "$RUN/server.pid" || alive "$RUN/mediamtx.pid"; then
  echo "이미 실행 중입니다. 먼저 scripts/stop.sh 를 실행하세요."; exit 1
fi
command -v mediamtx >/dev/null || { echo "mediamtx가 없습니다: brew install mediamtx"; exit 1; }

echo "서버 빌드 중..."
cargo build --release --manifest-path server-rs/Cargo.toml
TARGET=$(cargo metadata --no-deps --format-version 1 --manifest-path server-rs/Cargo.toml \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["target_directory"])')

export HOST="${HOST:-0.0.0.0}"
nohup "$TARGET/release/lecture-server" >"$RUN/server.log" 2>&1 &
echo $! >"$RUN/server.pid"
sleep 1   # MediaMTX가 인증 요청을 보내므로 서버를 먼저 띄운다
nohup mediamtx server/mediamtx.yml >"$RUN/mediamtx.log" 2>&1 &
echo $! >"$RUN/mediamtx.pid"
sleep 1

for n in server mediamtx; do
  alive "$RUN/$n.pid" && echo "$n 실행 중 (PID $(cat "$RUN/$n.pid"))" \
    || { echo "$n 시작 실패 — 로그: $RUN/$n.log"; tail -5 "$RUN/$n.log"; }
done
IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<서버IP>")
echo "접속: http://localhost:${PORT:-8765}  (다른 PC: http://$IP:${PORT:-8765})"
echo "로그: $RUN/server.log, $RUN/mediamtx.log"
