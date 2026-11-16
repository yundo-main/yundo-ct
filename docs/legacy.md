# 이전 Python 코드 (보관용)

강의도구 서버는 **Rust(`server-rs/`)**, 그림판은 **Rust + Tauri(`paint-rs/`)**로 전환했다. 이전 Python 코드는 삭제하지 않고 [`legacy/`](../legacy/)로 옮겨 두었다. 새 기능은 Rust 쪽에만 추가한다.

## 보관 위치

```text
legacy/
├── python-server/            # FastAPI 서버 (마지막 상태: Rust와 기능 동일)
│   ├── requirements-server.txt
│   └── server/               # main.py, auth.py, rooms.py, recorder.py, tests/
├── pyside6-paint/            # PySide6 그림판 (app/, main.py, tests/, assets/, requirements.txt)
├── tkinter-paint/            # 예전 tkinter 그림판(app/application.py)과 그 테스트
└── test-data/chatlogs/       # 옛 자동 테스트가 남긴 대화 기록(c5, h1)
```

## 필요하면 다시 실행하기 — 파이썬 서버

```bash
cd legacy/python-server
source ~/.venvs/yundo-ct/bin/activate
pip install -r requirements-server.txt
uvicorn server.main:app --port 8765          # 화면은 프로젝트 루트의 web/ 를 읽는다
python -m unittest discover -s server/tests  # 15건
```

- Rust 서버와 **같은 포트(8765)를 쓰므로 둘 중 하나만** 띄운다.
- 데이터 폴더는 환경변수로 지정한다: `CHATLOG_DIR`, `RECORDINGS_DIR`, `UPLOAD_DIR`(기본값은 `legacy/python-server/server/` 아래라서, 프로젝트의 `server/chatlogs` 등을 쓰려면 지정해야 한다).
- 토큰 형식이 같아서 `LECTURE_SECRET`이 같으면 두 서버의 토큰이 서로 통한다.

## 필요하면 다시 실행하기 — PySide6 그림판

```bash
cd legacy/pyside6-paint
source ~/.venvs/yundo-ct/bin/activate
pip install -r requirements.txt
python main.py                                   # 실행 (F1: 도움말)
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v   # 테스트 20건
```

새 그림판(`paint-rs/`)은 이 앱의 도구 12종·글씨·칠판 색·눈금·격자·확대·파일 브라우저·도움말·저장 확인을 모두 옮겼다. 다만 이 앱에만 있던 "칠판색에 맞춘 펜 색 자동 보정"과 "글꼴 패널" 일부 동작은 옮기지 않았다.

## 전환 기록 요약

- 파이썬과 Rust 서버는 모든 기능을 같은 동작으로 구현하고 같은 시나리오로 테스트했다(파이썬 15건 / Rust 18건).
- 전환 후에는 Rust 서버가 실제 브라우저·MediaMTX 환경에서 동작하는지 확인했다. 자세한 내용은 [devlog.md](devlog.md)의 18번.
