# 강의도구 · 그림판 (Rust)

영상 강의 위에서 실시간으로 판서하고, 수강생이 같은 화면을 보며 참여(퀴즈·설문·질문·채팅·화면 공유)하는 **강의도구**와, 보조 도구인 **그림판**입니다. 모두 Rust 기반입니다.

Produced by yundo

## 구성

| 폴더 | 내용 |
|---|---|
| [server-rs/](server-rs/README.md) | 강의도구 서버 (Rust, axum): 로그인, MediaMTX 인증, WebSocket 실시간 기능, 녹화·채팅·파일 |
| [web/](web/) | 브라우저 화면 (강의 화면 `index.html`, 다시보기 `replay.html`). 서버 실행 파일에 포함됨 |
| [paint-rs/](paint-rs/README.md) | 그림판 (Rust + Tauri) |
| [server/](server/) | MediaMTX 설정(`mediamtx.yml`)과 실행 중 생기는 데이터(채팅 로그, 녹화 이벤트, 업로드) |
| [docs/](docs/) | 개발 문서 |
| [legacy/](docs/legacy.md) | 이전 Python 코드(보관용): 파이썬 서버, PySide6 그림판, tkinter 그림판 |

## 실행

```bash
# 한 번에 백그라운드 실행 / 종료 (서버 + MediaMTX)
scripts/start.sh
scripts/stop.sh

# 또는 각각 직접 실행
# 강의도구 서버 (프로젝트 루트에서) → http://localhost:8765
cargo run --release --manifest-path server-rs/Cargo.toml
mediamtx server/mediamtx.yml            # 영상 송출·시청용, 별도 터미널 (brew install mediamtx)

# 그림판
cd paint-rs/src-tauri && cargo run
```

빌드 산출물은 Google Drive 밖(`~/.cache/yundo-ct-target`)에 쌓이도록 `.cargo/config.toml`에서 지정했습니다(다른 PC에서는 경로를 바꾸세요).

## 테스트

```bash
cargo test --manifest-path server-rs/Cargo.toml     # 서버 통합 테스트
cargo test --manifest-path paint-rs/src-tauri/Cargo.toml   # 그림판 Rust 단위 테스트
```

## 문서

- 사용 설명서·문제 해결: [docs/manual.md](docs/manual.md)
- 개발 기록: [docs/devlog.md](docs/devlog.md), 로드맵: [docs/roadmap.md](docs/roadmap.md)
- 서버 API·메시지 규약: [docs/server-api.md](docs/server-api.md)
- 이전 Python 코드를 다시 실행하는 방법: [docs/legacy.md](docs/legacy.md)
- 초기 계획과 PySide6 그림판 점검 기록(역사 자료): [docs/plan.md](docs/plan.md), [docs/ui-checklist.md](docs/ui-checklist.md)
