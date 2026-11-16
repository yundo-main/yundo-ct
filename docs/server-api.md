# 강의도구 서버 API·메시지 규약

서버는 **Rust(axum)** 한 벌이다(`server-rs/`). 영상은 MediaMTX(WebRTC), 상호작용 데이터는 WebSocket이 맡는다.
이 문서는 서버가 주고받는 API와 메시지 규약을 설명한다. 코드 구조와 실행 방법은 [../server-rs/README.md](../server-rs/README.md),
개발 기록은 [devlog.md](devlog.md), 이전 파이썬 서버는 [legacy.md](legacy.md)를 본다.

## 구성

```text
server-rs/            # Rust 서버 (코드, 테스트)
server/
├── mediamtx.yml      # MediaMTX 설정(외부 HTTP 인증 → /api/mediamtx/auth)
└── chatlogs/ ...     # 실행 중 생기는 데이터(채팅 로그, 녹화 이벤트, 업로드 파일)
web/                  # 브라우저 화면 (index.html 강사/수강생 공용, replay.html 다시보기). Rust 서버가 빌드 때 포함
```

## 실행

```bash
cargo run --release --manifest-path server-rs/Cargo.toml   # http://localhost:8765 (프로젝트 루트에서)
mediamtx server/mediamtx.yml                                 # 별도 터미널 (brew install mediamtx)
cargo test --manifest-path server-rs/Cargo.toml
```

> `mediamtx.yml`의 `authHTTPAddress` 포트는 서버 포트(`PORT`, 기본 8765)와 같아야 한다. 포트를 바꾸면 둘 다 수정.
> 화면(`web/`)을 고친 뒤에는 서버를 다시 빌드해야 반영된다.

- 관리자: 이름 `admin` / 비밀번호 `admin` (환경변수 `ADMIN_PASSWORD`) — 강사와 동일 권한
- 강사: 이름 `teacher` / 비밀번호 `teacher` (환경변수 `TEACHER_PASSWORD`, `LECTURE_SECRET`로 변경)
- 강사 송출: 페이지 상단의 **📷 카메라 / 🖥 화면 공유 / 🪟 창 공유** 버튼 (`getUserMedia`/`getDisplayMedia` → WHIP → MediaMTX). 수강생은 읽기 전용 시청. macOS는 브라우저에 화면 기록 권한 필요.
- 수강생: 아무 이름, 비밀번호 비움
- 방은 서버가 살아있는 한 유지된다. 새 입장자는 이전 채팅 기록(최대 200개, DM은 당사자만)을 STATE로 받고, 서버 재시작 후엔 `server/chatlogs/` 파일에서 복원한다.

## 메시지 규약 `{type, payload}`

| type | 보내는 쪽 | 설명 |
|---|---|---|
| DRAW / CLEAR | 강사 | 정규화 좌표(0~1) 판서, 전원에게 전달 |
| MOVE | 강사 | 판서 개체(글씨·도형·아이콘·펜 획)를 `{oid, dx, dy}`만큼 이동(화면 비율, -1~1). 서버가 TEXT/SHAPE/ICON/DRAW(펜)에 붙여 주는 `oid`로 개체를 가리키며, 보관 중인 판서도 옮겨서 늦게 입장한 사람은 옮겨진 위치를 받는다. 지우개 획에는 `oid`가 없어 옮길 수 없다 |
| SNIPPET | 강사 | 코드 블록 + 복사 버튼 |
| QUIZ_START / QUIZ_END | 강사 | OX 퀴즈 발행/종료 |
| QUIZ_ANSWER | 수강생 | 선택 인덱스, 집계는 강사에게만 QUIZ_RESULT |
| SURVEY_START / SURVEY_END | 강사 | 설문 발행/종료 (익명 옵션), 전원에게 실시간 SURVEY_RESULT 집계 |
| SURVEY_ANSWER | 수강생 | 선택 인덱스. 실명 설문이면 투표 명단을 강사에게만 SURVEY_VOTERS |
| QUESTION / QUESTION_DONE | 수강생 / 강사 | 질문 큐, 답변 완료 체크 |
| CHAT | 모두 | 채팅 메시지 `{name, text}` (500자 제한), 녹화·채팅 로그에 포함 |
| DM | 모두 | 귓속말 `{to, text}` — 발신자·수신자에게만 전달, 채팅 로그에 포함 |
| MEMBERS | 서버 | 입장/퇴장 시 접속자 명단 브로드캐스트 |
| HAND | 수강생 | 손들기(강사에게만) |
| REC_START / REC_STOP | 강사 | 상호작용 녹화 시작/종료, 전원에게 REC_STATE 알림 |

### 강의자 계정과 로그인 구분

- `POST /api/login`의 `kind`: `"staff"`(강의자 탭 — 등록된 아이디+비밀번호만), `"student"`(수강생 탭 — 강의자 아이디는 사용 불가), 생략하면 이전 방식. 화면의 로그인 탭이 이 값을 보낸다.
- 기본 계정은 `teacher`/`admin`(비밀번호는 `TEACHER_PASSWORD`/`ADMIN_PASSWORD`). 강의자를 더 추가하려면 `TEACHER_ACCOUNTS="아이디:비밀번호,아이디2:비밀번호2"`(양쪽 서버 공통, 쉼표·콜론은 비밀번호에 쓸 수 없음).

### 수강생 화면 공유

- 수강생 `SHARE_REQUEST` → 강의자 `SHARE_GRANT {name}`(요청한 사람만, 한 번에 한 명) 또는 `SHARE_DENY {name}`. 끝내기는 발표자 `SHARE_END` 또는 강의자 `SHARE_STOP`, 요청 취소는 `SHARE_CANCEL`.
- 서버는 상태가 바뀔 때마다 `SHARE_STATE {presenter, requests, requested}`를 보낸다(`requests`는 강의자에게만, 수강생은 자기 요청 여부 `requested`만). 입장 시 `STATE.share`로도 전달.
- 영상 경로는 `{방}__share`. MediaMTX 인증 훅이 이 경로의 publish를 **지금 발표자인 그 수강생**에게만 허용하고, 강의 영상 경로(`{방}`)는 강의자 전용으로 유지한다. 발표자가 나가면 상태가 정리된다.
- 한계: 허용이 취소돼도 이미 연결된 송출을 서버가 끊지는 못한다(화면이 중지 신호를 받아 스스로 끊는다). 강제 종료는 MediaMTX API 연동이 필요하다.

### 채팅 파일 첨부

- `POST /api/upload/{room}?token=&name=파일이름` — 본문이 파일 바이트. 방에 입장해 있는 사람만 올릴 수 있고(20MB 이하, 실행 파일 형식 거부), 성공하면 방 전원에게 `CHAT`(`payload.file = {id, name, size}`)이 간다. 파일은 `server/uploads/{room}/{id}/{이름}`(환경변수 `UPLOAD_DIR`)에 저장된다.
- `GET /api/files/{room}/{id}/{이름}?token=` — 내려받기(항상 attachment, `nosniff`). 이미지(png/jpg/gif/webp)만 `&inline=1`로 화면에 직접 표시한다.
- 첨부 기록도 채팅 로그에 `file`로 남아 재입장·재시작 후에 복원된다. 파일은 자동 삭제되지 않는다(보관 기간 정책은 로드맵 단계 5).

채팅 로그는 녹화 여부와 무관하게 `server/chatlogs/{room}/chat.jsonl`에 저장되며, `GET /api/chatlog/{room}?token=`으로 강사만 조회할 수 있다.

강사 전용 메시지를 수강생이 보내면 ERROR로 거부한다. 늦게 입장하면 STATE로 현재 퀴즈·질문을 받는다.

## 한계 / 다음 단계

- 사용자 계정은 데모용(메모리). 운영 시 DB, 비밀번호 해시, HTTPS 필요.
- 방 상태는 메모리 보관이라 서버 재시작 시 사라진다. 서버를 여러 대로 늘리려면 Redis pub/sub 필요.
- 브라우저 화면은 최소 구현이며 영상은 MediaMTX 내장 WebRTC 페이지를 iframe으로 사용한다. 실제 영상 송출은 MediaMTX 실행 후 수동 확인이 필요하다.
- 그림판 앱과의 연동(그림판에서 그린 이미지를 강의 화면에 공유)은 미구현.

## 녹화

두 가지를 따로 저장하고 다시보기에서 합친다.

1. **영상**: MediaMTX가 송출 시작과 동시에 자동 저장한다 (`mediamtx.yml`의 `record`, fmp4, 1시간 단위 분할, 30일 후 삭제).
   다시보기 재생 서버는 포트 9996 (`playback`).
2. **상호작용**: 강사가 화면의 `● 녹화 시작`을 누르면 서버가 판서·코드 스니펫·퀴즈·질문을
   `server/recordings/<방>/<날짜-시간>.jsonl`에 `{t(ms), type, payload, by}`로 기록한다. 강사가 모두 나가면 자동으로 닫힌다.

**다시보기**: `/replay` 에서 토큰, 녹화 파일, 영상 주소를 넣고 불러온다. 영상 재생 시간에 맞춰 판서가 다시 그려지고,
코드·질문 타임라인 항목을 누르면 해당 시점으로 이동한다.

**동기 방법**: 이벤트의 0초는 `녹화 시작`을 누른 시점이다. 영상은 송출 시작부터 기록되므로,
송출 시작 직후에 녹화 시작을 누르고, 어긋나면 다시보기의 오프셋(ms)으로 맞춘다.

API: `GET /api/recordings`(강사), `GET /api/recordings/{방}/{파일}`(로그인한 사용자). 방 이름은 영문·숫자·`-_`만 녹화 가능.

**한계**: 영상과 이벤트 시각 자동 정렬은 미구현(수동 오프셋). 실제 영상 녹화·재생은 MediaMTX를 띄워 확인하지 않았다.
녹화 파일은 개인정보(수강생 이름, 질문)를 포함하므로 보관 기간과 접근 권한을 정해야 한다.
