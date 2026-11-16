# 강의도구 서버 (Rust / axum)

강의도구의 **유일한 서버**다(이전 파이썬 서버는 [`../legacy/python-server/`](../docs/legacy.md)로 보관).
브라우저 화면(`web/*.html`)은 빌드 때 실행 파일에 포함된다. 화면을 고치면 다시 빌드해야 반영된다.
API·메시지 규약과 기능 설명은 [../docs/server-api.md](../docs/server-api.md)를 따른다.

## 구조

```text
.cargo/config.toml     # (프로젝트 루트) 빌드 폴더를 Google Drive 밖(~/.cache)으로 지정
server-rs/
├── Cargo.toml
├── src/
│   ├── main.rs          # 실행 진입점 (HOST, PORT)
│   ├── lib.rs           # 라우팅, HTTP API, WebSocket, 메시지 처리
│   ├── auth.rs          # HMAC 토큰 (파이썬 서버와 상호 호환)
│   ├── config.rs        # 환경변수 설정
│   ├── rooms.rs         # 방 상태, 퀴즈/설문(Poll), 브로드캐스트
│   └── recorder.rs      # 이벤트 녹화(JSONL), 채팅 로그
└── tests/server_test.rs # 통합 테스트 18건
```

## 실행

프로젝트 루트(`yundo-ct/`)에서 실행한다. 녹화·채팅 로그 기본 경로가 루트 기준이기 때문이다.

```bash
cargo run --release --manifest-path server-rs/Cargo.toml
# 또는 빌드 후: ~/.cache/yundo-ct-target/release/lecture-server
cargo test --manifest-path server-rs/Cargo.toml
```

| 환경변수 | 기본값 |
|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8765` |
| `LECTURE_SECRET` | `dev-secret-change-me` (운영 시 반드시 변경) |
| `TEACHER_PASSWORD` / `ADMIN_PASSWORD` | `teacher` / `admin` |
| `RECORDINGS_DIR` / `CHATLOG_DIR` / `UPLOAD_DIR` | `server/recordings` / `server/chatlogs` / `server/uploads` |

legacy의 파이썬 서버와 같은 포트·같은 폴더·같은 토큰 형식을 쓰므로, 필요하면 둘 중 하나만 띄운다.

## 파이썬 서버와의 차이

- 잘못된 토큰은 WebSocket 연결 단계에서 HTTP 403으로 거절한다(파이썬도 같은 결과).
- 클라이언트가 JSON이 아닌 메시지를 보내면 연결을 끊지 않고 무시한다(파이썬은 연결이 끊김).
- 녹화·채팅 파일 쓰기에 실패해도 강의 진행은 멈추지 않는다.

## 파이썬 서버에서 그대로 옮긴 동작 (개선 후보)

옮기면서 일부러 바꾸지 않았다. 의도인지 확인이 필요하다.

- 퀴즈 집계(`QUIZ_RESULT`)와 손들기(`HAND`)는 역할이 `teacher`인 사람에게만 가고, `admin`에게는 가지 않는다.
- 녹화 자동 종료는 `teacher`가 모두 나갔을 때만 동작한다. `admin`만 있던 방은 녹화가 계속 열려 있다.
- 방 이름은 아무 값이나 접속할 수 있고, 녹화·채팅 저장만 영문·숫자·`-_`(64자 이하)로 제한된다.
