"""강의도구 서버: 인증 + MediaMTX 연동 + 실시간 강의 도구(판서/코드공유/퀴즈/질문큐).

실행: uvicorn server.main:app --reload --port 8000
"""

import json
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server import auth, recorder
from server.rooms import ConnectionManager, Member

STATIC = Path(__file__).resolve().parents[3] / "web"  # 화면은 server/ 밖의 web/ 에 둔다
app = FastAPI(title="강의도구 서버")
manager = ConnectionManager()

BOARD_BGS = {"video", "white", "green", "black", "grid"}
TEACHER_ONLY = {"SHAPE", "ICON", "BOARD_BG", "SHARE_GRANT", "SHARE_DENY", "SHARE_STOP", "TEXT", "DRAW", "CLEAR", "SNIPPET", "QUIZ_START", "QUIZ_END", "QUESTION_DONE", "REC_START", "REC_STOP", "SURVEY_START", "SURVEY_END"}
STAFF = {"teacher", "admin"}


class LoginBody(BaseModel):
    name: str
    password: str = ""
    kind: str = "auto"  # "student" | "staff" | "auto"


@app.post("/api/login")
def login(body: LoginBody):
    kind = body.kind if body.kind in ("student", "staff") else "auto"
    token = auth.login(body.name, body.password, kind)
    if not token:
        if kind == "student" and body.name in auth.USERS:
            raise HTTPException(401, "강의자 아이디는 수강생 이름으로 쓸 수 없습니다. 강의자 탭에서 입장하세요.")
        raise HTTPException(401, "강의자 아이디 또는 비밀번호가 올바르지 않습니다." if kind == "staff" else "이름 또는 비밀번호가 올바르지 않습니다.")
    return {"token": token, "role": auth.verify_token(token)["role"]}


class MediaMTXAuth(BaseModel):
    """MediaMTX externalAuthenticationURL 요청 본문(일부)."""
    user: str = ""
    password: str = ""
    token: str = ""
    action: str = ""
    path: str = ""
    query: str = ""


SHARE_SUFFIX = "__share"  # 수강생 화면 공유 영상 경로: {방}__share


@app.post("/api/mediamtx/auth")
def mediamtx_auth(req: MediaMTXAuth):
    """publish는 강사만, read는 로그인한 누구나. 토큰은 password/token/query(token=) 로 전달."""
    token = req.token or req.password
    if not token and "token=" in req.query:
        token = req.query.split("token=", 1)[1].split("&", 1)[0]
    claims = auth.verify_token(token)
    if not claims:
        raise HTTPException(401)
    if req.action == "publish":
        path = req.path.lstrip("/")
        if path.endswith(SHARE_SUFFIX):
            # 수강생 화면 공유 경로: 강의자가 허용해서 지금 발표자인 그 수강생만 올릴 수 있다
            room = manager.rooms.get(path[: -len(SHARE_SUFFIX)])
            if claims["role"] in STAFF or not room or room.presenter != claims["name"]:
                raise HTTPException(403)
        elif claims["role"] not in STAFF:
            raise HTTPException(403)
    return {}


MAX_UPLOAD = 20 * 1024 * 1024  # 채팅 첨부 파일 최대 크기(20MB)
BLOCKED_EXT = {"exe", "bat", "cmd", "com", "scr", "msi", "ps1", "vbs", "jar", "app", "dmg", "sh"}  # 실행 파일은 막는다
INLINE_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def clean_filename(name: str) -> str:
    """경로 구분자·제어문자·특수문자를 없애 안전한 파일 이름으로 만든다(100자까지). Rust 서버와 같은 규칙."""
    name = re.split(r"[\\/]", str(name))[-1]
    name = "".join("_" if c in ':*?"<>|' else c for c in name if c.isprintable())
    name = name.strip(" .")[:100].strip(" .")
    return name or "file"


@app.post("/api/upload/{room_id}")
async def upload(room_id: str, request: Request, token: str = Query(""), name: str = Query("file")):
    """채팅 첨부 파일 올리기. 본문은 파일 바이트 그대로이고, 올리면 방 전원에게 CHAT(file 포함)으로 알린다."""
    claims = auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "Unauthorized")
    try:
        room_dir = recorder.safe_room(room_id)
    except ValueError:
        raise HTTPException(400, "올릴 수 없는 방 이름입니다.")
    room = manager.room(room_id)
    if not any(m.name == claims["name"] for m in room.members):
        raise HTTPException(403, "방에 입장한 사람만 올릴 수 있습니다.")
    fname = clean_filename(name)
    if fname.rsplit(".", 1)[-1].lower() in BLOCKED_EXT and "." in fname:
        raise HTTPException(400, "이 형식의 파일은 올릴 수 없습니다.")
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
        raise HTTPException(413, "파일은 20MB까지 올릴 수 있습니다.")
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD:
            raise HTTPException(413, "파일은 20MB까지 올릴 수 있습니다.")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(400, "빈 파일입니다.")
    fid = secrets.token_hex(6)
    folder = recorder.UPLOAD_DIR / room_dir / fid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / fname).write_bytes(b"".join(chunks))
    file = {"id": fid, "name": fname, "size": total}
    payload = {"name": claims["name"], "text": "", "file": file}
    room.chat_history.append(dict(payload))
    await manager.broadcast(room_id, {"type": "CHAT", "payload": payload})
    if room.recorder is not None:
        room.recorder.write("CHAT", payload, claims["name"])
    recorder.log_chat(room_id, claims["name"], "", file=file)
    return file


@app.get("/api/files/{room_id}/{file_id}/{name}")
def download(room_id: str, file_id: str, name: str, token: str = Query(""), inline: int = Query(0)):
    if not auth.verify_token(token):
        raise HTTPException(401, "Unauthorized")
    try:
        room_dir = recorder.safe_room(room_id)
    except ValueError:
        raise HTTPException(404)
    path = recorder.UPLOAD_DIR / room_dir / file_id / clean_filename(name)
    if not re.fullmatch(r"[0-9a-f]{12}", file_id) or clean_filename(name) != name or not path.is_file():
        raise HTTPException(404, "Not Found")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    headers = {"X-Content-Type-Options": "nosniff"}
    if inline and ext in INLINE_EXT:  # 이미지 미리보기만 화면에 직접 표시하고, 나머지는 항상 내려받기로 처리한다
        return FileResponse(path, media_type=INLINE_EXT[ext], content_disposition_type="inline", headers=headers)
    return FileResponse(path, media_type="application/octet-stream", filename=name, headers=headers)


@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str, token: str = Query("")):
    claims = auth.verify_token(token)
    if not claims:
        await ws.close(code=4401)
        return
    member = Member(ws, claims["name"], claims["role"])
    room = await manager.join(room_id, member)
    if not room.chat_loaded:
        room.chat_loaded = True
        try:
            path = recorder.read_chatlog(room_id)
            if path:
                for line in path.read_text(encoding="utf-8").strip().split("\n")[-200:]:
                    item = json.loads(line)
                    entry = {"name": item["name"], "text": item["text"], "to": item.get("to", "")}
                    if item.get("file"):
                        entry["file"] = item["file"]
                    room.chat_history.append(entry)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    await _broadcast_members(room_id)
    # 늦게 입장한 사람에게 현재 상태 전달
    await ws.send_json({"type": "STATE", "payload": {
        "role": member.role,
        "quiz": room.quiz and {k: v for k, v in room.quiz.items() if k != "answers"},
        "tally": room.quiz_tally(),
        "survey": room.survey and {k: v for k, v in room.survey.items() if k != "votes"},
        "surveyTally": room.survey_tally(),
        "questions": room.questions,
        "recording": room.recorder is not None,
        "share": _share_state(room, member),
        "boardBg": room.board_bg,
        "chat": [c for c in room.chat_history if not c.get("to") or c.get("to") == member.name or c.get("name") == member.name],
    }})
    try:
        while True:
            msg = await ws.receive_json()
            await handle(room_id, member, msg)
    except WebSocketDisconnect:
        manager.leave(room_id, member)
        await _broadcast_members(room_id)
        room = manager.room(room_id)
        if not any(m.name == member.name for m in room.members) and (
            member.name == room.presenter or member.name in room.share_requests
        ):  # 공유 중이거나 요청 중이던 수강생이 완전히 나가면 정리한다
            if room.presenter == member.name:
                room.presenter = None
            if member.name in room.share_requests:
                room.share_requests.remove(member.name)
            await _broadcast_share(room_id)
        # 강사가 모두 나가면 녹화 파일을 안전하게 닫는다
        if room.recorder and not any(m.role == "teacher" for m in room.members):
            room.recorder.stop()
            room.recorder = None
            await manager.broadcast(room_id, {"type": "REC_STATE", "payload": {"recording": False}})


def _share_state(room, member) -> dict:
    """화면 공유 상태. 대기 중인 요청 목록은 강의자에게만 보낸다."""
    state = {"presenter": room.presenter, "requests": [], "requested": member.name in room.share_requests}
    if member.role in STAFF:
        state["requests"] = list(room.share_requests)
    return state


async def _broadcast_share(room_id: str) -> None:
    room = manager.room(room_id)
    for m in list(room.members):
        try:
            await m.ws.send_json({"type": "SHARE_STATE", "payload": _share_state(room, m)})
        except Exception:
            pass


async def _broadcast_members(room_id: str) -> None:
    room = manager.room(room_id)
    await manager.broadcast(room_id, {"type": "MEMBERS", "payload": {
        "members": [{"name": m.name, "role": m.role} for m in room.members],
    }})


def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(x, lo), hi) if x == x else default


def _clean_text(p: dict) -> dict:
    """판서 텍스트: 좌표·크기는 범위로 제한하고 색은 #rrggbb만 허용한다. 길이는 200자까지."""
    color = p.get("color")
    return {
        "x": _num(p.get("x"), 0.0, 0.0, 1.0),
        "y": _num(p.get("y"), 0.0, 0.0, 1.0),
        "text": str(p.get("text", ""))[:200],
        "color": color if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#ff3b30",
        "size": _num(p.get("size"), 0.032, 0.01, 0.15),
    }


DRAW_MODES = {"pen", "dash", "highlight", "erase"}  # 실선 펜 / 점선 펜 / 형광펜 / 지우개
SHAPE_KINDS = {"line", "arrow", "rect", "ellipse"}
ICON_NAMES = {"check", "x", "star", "question", "bang", "heart", "bulb", "arrow", "flag", "smile"}


def _color(c) -> str:
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "#ff3b30"


def _clean_draw(p: dict) -> dict:
    """판서 점: 좌표·굵기는 범위로 제한하고 색은 #rrggbb만, 종류는 정해진 값만 허용한다. 굵기 w는 화면 높이에 대한 비율."""
    return {
        "x": _num(p.get("x"), 0.0, 0.0, 1.0), "y": _num(p.get("y"), 0.0, 0.0, 1.0),
        "color": _color(p.get("color")),
        "isDragging": p.get("isDragging") is True,
        "mode": p.get("mode") if p.get("mode") in DRAW_MODES else "pen",
        "w": _num(p.get("w"), 0.005, 0.001, 0.2),
    }


def _clean_shape(p: dict) -> dict | None:
    """도형: 종류는 정해진 값만, 좌표는 0~1로 제한한다."""
    if p.get("kind") not in SHAPE_KINDS:
        return None
    return {
        "kind": p["kind"],
        "x1": _num(p.get("x1"), 0.0, 0.0, 1.0), "y1": _num(p.get("y1"), 0.0, 0.0, 1.0),
        "x2": _num(p.get("x2"), 0.0, 0.0, 1.0), "y2": _num(p.get("y2"), 0.0, 0.0, 1.0),
        "color": _color(p.get("color")),
        "fill": p.get("fill") is True,
        "w": _num(p.get("w"), 0.005, 0.001, 0.2),
    }


def _clean_icon(p: dict) -> dict | None:
    """아이콘: 이름은 정해진 값만, 위치·크기는 범위로 제한한다."""
    if p.get("icon") not in ICON_NAMES:
        return None
    return {
        "icon": p["icon"],
        "x": _num(p.get("x"), 0.5, 0.0, 1.0), "y": _num(p.get("y"), 0.5, 0.0, 1.0),
        "size": _num(p.get("size"), 0.08, 0.02, 0.4),
        "color": _color(p.get("color")),
    }


async def handle(room_id: str, member: Member, msg: dict) -> None:
    room = manager.room(room_id)
    t, p = msg.get("type"), msg.get("payload", {})
    if t in TEACHER_ONLY and member.role not in STAFF:
        await member.ws.send_json({"type": "ERROR", "payload": {"message": "강사만 사용할 수 있습니다."}})
        return

    if t == "REC_START":
        if room.recorder is None:
            try:
                room.recorder = recorder.Recorder(room_id)
            except ValueError:
                await member.ws.send_json({"type": "ERROR", "payload": {"message": "녹화할 수 없는 방 이름입니다."}})
                return
        await manager.broadcast(room_id, {"type": "REC_STATE", "payload": {"recording": True}})
        return
    if t == "REC_STOP":
        if room.recorder is not None:
            room.recorder.stop()
            room.recorder = None
        await manager.broadcast(room_id, {"type": "REC_STATE", "payload": {"recording": False}})
        return
    if t == "TEXT":
        p = _clean_text(p if isinstance(p, dict) else {})
        if not p["text"].strip():
            return
    if t == "DRAW":
        p = _clean_draw(p if isinstance(p, dict) else {})
    if t in ("SHAPE", "ICON"):
        p = (_clean_shape if t == "SHAPE" else _clean_icon)(p if isinstance(p, dict) else {})
        if p is None:
            return
    if t == "BOARD_BG":
        bg = p.get("bg") if isinstance(p, dict) else None
        if bg not in BOARD_BGS:
            return
        p = {"bg": bg}
        room.board_bg = bg
    if room.recorder is not None and t in recorder.RECORDED_TYPES:
        room.recorder.write(t, p if t != "SNIPPET" else {"text": str(p.get("text", ""))[:4000]}, member.name)

    if t in ("DRAW", "CLEAR", "TEXT", "SHAPE", "ICON", "BOARD_BG"):
        await manager.broadcast(room_id, {"type": t, "payload": p})
    elif t == "SNIPPET":
        await manager.broadcast(room_id, {"type": t, "payload": {"text": str(p.get("text", ""))[:4000]}})
    elif t == "QUIZ_START":
        options = [str(o) for o in p.get("options", ["O", "X"])][:6]
        room.quiz = {"id": len(room.questions) + 1000, "question": str(p.get("question", "")),
                     "options": options, "answers": {}}
        await manager.broadcast(room_id, {"type": t, "payload": {k: v for k, v in room.quiz.items() if k != "answers"}})
    elif t == "QUIZ_ANSWER" and room.quiz:
        idx = p.get("choice")
        if isinstance(idx, int) and 0 <= idx < len(room.quiz["options"]):
            room.quiz["answers"][member.name] = idx
            await manager.broadcast(room_id, {"type": "QUIZ_RESULT", "payload": {"tally": room.quiz_tally()}},
                                    only_role="teacher")
    elif t == "QUIZ_END" and room.quiz:
        await manager.broadcast(room_id, {"type": t, "payload": {"tally": room.quiz_tally()}})
        room.quiz = None
    elif t == "SURVEY_START":
        options = [str(o) for o in p.get("options", []) if str(o).strip()][:6]
        if not options:
            await member.ws.send_json({"type": "ERROR", "payload": {"message": "선택지가 필요합니다."}})
            return
        room.survey = {"id": next(room._qid), "question": str(p.get("question", "")),
                       "options": options, "anonymous": bool(p.get("anonymous")), "votes": {}}
        await manager.broadcast(room_id, {"type": t, "payload": {k: v for k, v in room.survey.items() if k != "votes"}})
    elif t == "SURVEY_ANSWER" and room.survey:
        idx = p.get("choice")
        if isinstance(idx, int) and 0 <= idx < len(room.survey["options"]):
            room.survey["votes"][member.name] = idx
            await manager.broadcast(room_id, {"type": "SURVEY_RESULT", "payload": {
                "tally": room.survey_tally(), "voted": len(room.survey["votes"]),
            }})
            if not room.survey["anonymous"]:
                await manager.broadcast(room_id, {"type": "SURVEY_VOTERS", "payload": {
                    "votes": room.survey["votes"],
                }}, only_role="teacher")
    elif t == "SURVEY_END" and room.survey:
        await manager.broadcast(room_id, {"type": t, "payload": {"tally": room.survey_tally()}})
        room.survey = None
    elif t == "QUESTION":
        q = {"id": next(room._qid), "name": member.name, "text": str(p.get("text", ""))[:500], "done": False}
        room.questions.append(q)
        await manager.broadcast(room_id, {"type": t, "payload": q})
    elif t == "QUESTION_DONE":
        for q in room.questions:
            if q["id"] == p.get("id"):
                q["done"] = True
        await manager.broadcast(room_id, {"type": t, "payload": {"id": p.get("id")}})
    elif t == "CHAT":
        text = str(p.get("text", ""))[:500]
        room.chat_history.append({"name": member.name, "text": text})
        await manager.broadcast(room_id, {"type": t, "payload": {"name": member.name, "text": text}})
        try:
            recorder.log_chat(room_id, member.name, text)
        except ValueError:
            pass
    elif t == "DM":
        target_name = str(p.get("to", ""))
        text = str(p.get("text", ""))[:500]
        targets = [m for m in room.members if m.name == target_name]
        if not targets:
            await member.ws.send_json({"type": "ERROR", "payload": {"message": "상대를 찾을 수 없습니다."}})
            return
        dm = {"type": t, "payload": {"from": member.name, "to": target_name, "text": text}}
        for m in targets:
            await m.ws.send_json(dm)
        await member.ws.send_json(dm)
        room.chat_history.append({"name": member.name, "text": text, "to": target_name})
        try:
            recorder.log_chat(room_id, member.name, text, to=target_name)
        except ValueError:
            pass
    elif t == "SHARE_REQUEST":
        if member.role in STAFF or room.presenter == member.name:
            return
        if member.name not in room.share_requests:
            room.share_requests.append(member.name)
        await _broadcast_share(room_id)
    elif t == "SHARE_CANCEL":
        if member.name in room.share_requests:
            room.share_requests.remove(member.name)
            await _broadcast_share(room_id)
    elif t == "SHARE_GRANT":
        name = str(p.get("name", ""))
        if name in room.share_requests:  # 요청한 사람에게만 허용할 수 있다. 한 번에 한 명만 공유한다.
            room.share_requests.remove(name)
            room.presenter = name
            await _broadcast_share(room_id)
    elif t == "SHARE_DENY":
        name = str(p.get("name", ""))
        if name in room.share_requests:
            room.share_requests.remove(name)
            await _broadcast_share(room_id)
    elif t in ("SHARE_STOP", "SHARE_END"):
        if t == "SHARE_STOP" or room.presenter == member.name:
            if room.presenter is not None:
                room.presenter = None
                await _broadcast_share(room_id)
    elif t == "HAND":
        await manager.broadcast(room_id, {"type": t, "payload": {"name": member.name}}, only_role="teacher")


def _require_teacher(token: str) -> None:
    claims = auth.verify_token(token)
    if not claims or claims["role"] not in STAFF:
        raise HTTPException(403, "강사만 접근할 수 있습니다.")


@app.get("/api/recordings")
def recordings(token: str = Query("")):
    _require_teacher(token)
    return recorder.list_recordings()


@app.get("/api/recordings/{room_id}/{file}")
def recording_events(room_id: str, file: str, token: str = Query("")):
    """다시보기용 이벤트 로그. 강의에 로그인한 사람이면 볼 수 있다."""
    if not auth.verify_token(token):
        raise HTTPException(401)
    try:
        path = recorder.read_recording(room_id, file)
    except ValueError:
        path = None
    if not path:
        raise HTTPException(404)
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="application/x-ndjson")


@app.get("/api/chatlog/{room_id}")
def chatlog(room_id: str, token: str = Query("")):
    """방 채팅 로그. 강사만 조회 가능."""
    _require_teacher(token)
    try:
        path = recorder.read_chatlog(room_id)
    except ValueError:
        path = None
    if not path:
        raise HTTPException(404)
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="application/x-ndjson")


@app.get("/replay")
def replay():
    return FileResponse(STATIC / "replay.html")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
