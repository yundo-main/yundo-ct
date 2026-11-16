# 그림판 (Rust + Tauri)

PySide6 그림판을 Rust로 다시 만든 것이다(이전 앱은 [`legacy/pyside6-paint/`](../docs/legacy.md)에 보관). **Tauri**를 쓴다: 화면은 `ui/`의 웹 화면(HTML/JS)이고, 파일 열기·저장 같은 운영체제 기능은 Rust(`src-tauri/src/lib.rs`)가 맡는다. 단일 실행 파일로 배포할 수 있고 Windows·macOS 모두 지원한다(Windows는 WebView2 필요, Windows 11은 기본 설치).

## 구조

```text
paint-rs/
├── ui/index.html           # 화면과 그리기 (캔버스, 도구, 색, 칠판 색, 실행 취소, 테마, 확대, 눈금, 격자, 파일 브라우저, 도움말)
└── src-tauri/
    ├── Cargo.toml, build.rs, tauri.conf.json
    ├── icons/icon.png
    ├── capabilities/default.json   # 화면이 "창 닫기 요청" 이벤트를 받을 권한
    └── src/
        ├── main.rs         # 진입점
        └── lib.rs          # 명령: save_png_as, save_png_to, open_image, read_image, list_dir, quit_app, close_cancelled (+ 단위 테스트)
```

## 실행·테스트

프로젝트 루트의 `.cargo/config.toml`이 빌드 폴더를 Google Drive 밖(`~/.cache/yundo-ct-target`)으로 돌린다.

```bash
cd paint-rs/src-tauri
cargo run                 # 개발 실행 (창이 열린다)
cargo build --release     # 릴리스: ~/.cache/yundo-ct-target/release/paint-rs
cargo test                # Rust 단위 테스트
```

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 연필, 지우개, 색(팔레트+직접 선택), 굵기, 실행 취소/다시 실행, 새로 만들기, PNG 열기/저장, 칠판 색 라디오, 다크 테마 | **구현·확인** |
| 2 | 브러시, 직선·사각형·타원(Shift로 45도·정사각형·정원, 채우기 옵션), 텍스트(한글 입력, 글꼴·크기), 색 채우기, 색 선택(스포이트), 영역 선택·삭제, 영역 삭제 도구 | **구현·확인** |
| 3 | 확대/축소(25~400%, Ctrl+휠), 눈금(px·cm·mm), 격자, 파일 브라우저(Ctrl+B), 도움말(F1), 창 닫기 전 저장 확인 | **구현·확인** |

1~3단계가 끝나 PySide6 앱은 `legacy/pyside6-paint/`로 옮겼다.

## 동작 메모

- 그림 층은 투명 캔버스이고 칠판 색은 그 뒤 배경이다. 그래서 **칠판 색을 바꿔도 그린 그림은 그대로**이고(PySide6 앱의 "가장자리 옅은 테두리" 문제 없음), 지우개는 그림 층만 지워 투명하게 만든다. 저장할 때 칠판 색을 깔아 합친다(칠판 색이 "투명"이면 투명 PNG).
- 이미지를 열면 캔버스 크기가 이미지 크기가 되고, 그 위에 이어서 그리거나 지울 수 있다.
- 실행 취소는 그린 순서대로의 기록(획·도형·글씨·채우기·삭제)을 다시 그리는 방식이다. 색 채우기도 기록에 들어 있어 취소·다시 실행이 된다.
- 도구 12개는 PySide6 앱과 같다: 연필 P, 브러시 B, 지우개 E, 직선 L, 사각형 R, 타원 O, 텍스트 T, 색 채우기 F, 색 선택 I, 선택 S, 영역 삭제 D, 선택 영역 삭제(Delete). 글씨는 Ctrl+Enter 또는 바깥 클릭으로 확정, Esc 취소.
- Ctrl+S는 이미 저장한 파일이면 같은 경로에 바로 저장한다. 단축키: P 연필, E 지우개, `[` `]` 굵기, Ctrl+Z/Y, Ctrl+N/O/S, Ctrl+Shift+S.

## 알려진 한계

- 닫기 확인: 창을 닫으면 Rust가 첫 요청을 막고 화면이 "저장하고 닫기 / 저장 안 함 / 취소"를 묻는다. 화면이 응답하지 못해도 닫기를 한 번 더 누르면 닫힌다.
- 눈금·격자는 보기용이며 저장되는 이미지에는 들어가지 않는다.
- 글씨 도구의 한글 입력은 실제 입력기(IME)로 확인하지 못했다(코드로 값을 넣어 시험). Tauri 앱에서 직접 한글을 쳐 보고 알려 주세요.
- 색 채우기는 가장자리 번짐(안티앨리어싱) 때문에 선 가장자리에 옅은 테두리가 남을 수 있다(오차 허용 64).
- 칠판 색이 어두울 때 검은 펜 색을 자동으로 바꾸는 기능은 아직 없다.
