"""상호작용 이벤트 녹화: 판서/스니펫/퀴즈/질문을 시작 시점 기준 ms 오프셋과 함께 JSONL로 저장한다."""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", Path(__file__).parent / "recordings"))
CHATLOG_DIR = Path(os.environ.get("CHATLOG_DIR", Path(__file__).parent / "chatlogs"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", Path(__file__).parent / "uploads"))
RECORDED_TYPES = {"SHAPE", "ICON", "BOARD_BG", "TEXT", "DRAW", "CLEAR", "SNIPPET", "QUIZ_START", "QUIZ_END", "QUESTION", "QUESTION_DONE", "CHAT", "SURVEY_START", "SURVEY_END"}
SAFE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_room(room_id: str) -> str:
    """파일 경로에 쓰이므로 안전한 문자만 허용한다."""
    if not SAFE.match(room_id):
        raise ValueError("invalid room id")
    return room_id


class Recorder:
    def __init__(self, room_id: str) -> None:
        folder = RECORDINGS_DIR / safe_room(room_id)
        folder.mkdir(parents=True, exist_ok=True)
        self.started_at = datetime.now().astimezone()
        self.path = folder / f"{self.started_at:%Y%m%d-%H%M%S}.jsonl"
        self._t0 = time.monotonic()
        self._fh = self.path.open("a", encoding="utf-8")
        self._line({"t": 0, "type": "REC_START", "wall": self.started_at.isoformat()})

    def _line(self, obj: dict) -> None:
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._fh.flush()

    def write(self, type_: str, payload: dict, by: str) -> None:
        if type_ in RECORDED_TYPES:
            self._line({"t": int((time.monotonic() - self._t0) * 1000), "type": type_, "payload": payload, "by": by})

    def stop(self) -> None:
        self._line({"t": int((time.monotonic() - self._t0) * 1000), "type": "REC_STOP"})
        self._fh.close()


def list_recordings() -> list[dict]:
    out = []
    if RECORDINGS_DIR.exists():
        for f in sorted(RECORDINGS_DIR.glob("*/*.jsonl"), reverse=True):
            out.append({"room": f.parent.name, "file": f.name, "size": f.stat().st_size})
    return out


def read_recording(room_id: str, file: str) -> Path | None:
    path = RECORDINGS_DIR / safe_room(room_id) / file
    if not re.match(r"^[0-9-]+\.jsonl$", file) or not path.is_file():
        return None
    return path


def log_chat(room_id: str, name: str, text: str, to: str | None = None, file: dict | None = None) -> None:
    """방별 채팅 로그. 강의 녹화 여부와 무관하게 저장한다. DM은 to에 수신자 이름."""
    folder = CHATLOG_DIR / safe_room(room_id)
    folder.mkdir(parents=True, exist_ok=True)
    line = {"ts": datetime.now().astimezone().isoformat(), "name": name, "text": text}
    if to:
        line["to"] = to
    if file:
        line["file"] = file
    with (folder / "chat.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_chatlog(room_id: str) -> Path | None:
    path = CHATLOG_DIR / safe_room(room_id) / "chat.jsonl"
    return path if path.is_file() else None
