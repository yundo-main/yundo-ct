import json
import os
import tempfile
import unittest
from pathlib import Path

from server import recorder

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def setUpModule():
    client.__enter__()  # 백그라운드 이벤트 루프를 명시적으로 시작/종료해 프로세스가 끝나도록 함


def tearDownModule():
    client.__exit__(None, None, None)


def login(name, password=""):
    return client.post("/api/login", json={"name": name, "password": password}).json()["token"]


class ServerTest(unittest.TestCase):
    def test_login_rules(self):
        self.assertEqual(client.post("/api/login", json={"name": "teacher", "password": "x"}).status_code, 401)
        self.assertEqual(client.post("/api/login", json={"name": "kim"}).json()["role"], "student")

    def test_mediamtx_auth(self):
        t, s = login("teacher", "teacher"), login("kim")
        post = lambda **k: client.post("/api/mediamtx/auth", json=k).status_code
        self.assertEqual(post(action="publish", password=t), 200)
        self.assertEqual(post(action="publish", password=s), 403)
        self.assertEqual(post(action="read", query=f"token={s}"), 200)
        self.assertEqual(post(action="read"), 401)

    def test_realtime_flow(self):
        t, s = login("teacher", "teacher"), login("kim")
        with client.websocket_connect(f"/ws/r1?token={t}") as tw, client.websocket_connect(f"/ws/r1?token={s}") as sw:
            # 입장 시 MEMBERS(전원)와 STATE(본인)가 발송됨
            for _ in range(3): tw.receive_json()
            for _ in range(2): sw.receive_json()
            tw.send_json({"type": "DRAW", "payload": {"x": 0.5, "y": 0.5}})
            self.assertEqual(sw.receive_json()["type"], "DRAW")
            tw.receive_json()  # 강사 본인에게도 브로드캐스트됨
            sw.send_json({"type": "DRAW", "payload": {}})
            self.assertEqual(sw.receive_json()["type"], "ERROR")
            tw.send_json({"type": "QUIZ_START", "payload": {"question": "?", "options": ["O", "X"]}})
            tw.receive_json(); sw.receive_json()
            sw.send_json({"type": "QUIZ_ANSWER", "payload": {"choice": 1}})
            self.assertEqual(tw.receive_json()["payload"]["tally"], [0, 1])
            sw.send_json({"type": "CHAT", "payload": {"text": "안녕하세요"}})
            for w in (tw, sw):
                msg = w.receive_json()
                self.assertEqual(msg["type"], "CHAT")
                self.assertEqual(msg["payload"], {"name": "kim", "text": "안녕하세요"})

    def test_text_tool(self):
        t, s = login("teacher", "teacher"), login("kim")
        with client.websocket_connect(f"/ws/tx1?token={t}") as tw, client.websocket_connect(f"/ws/tx1?token={s}") as sw:
            for _ in range(3): tw.receive_json()
            for _ in range(2): sw.receive_json()
            # 학생은 텍스트를 올릴 수 없다
            sw.send_json({"type": "TEXT", "payload": {"x": .1, "y": .1, "text": "x"}})
            self.assertEqual(sw.receive_json()["type"], "ERROR")
            # 값이 범위를 벗어나거나 이상해도 정리되어 전달된다
            tw.send_json({"type": "TEXT", "payload": {"x": 5, "y": -2, "text": "가" * 300, "color": "red", "size": 9}})
            msg = sw.receive_json()
            tw.receive_json()
            self.assertEqual(msg["type"], "TEXT")
            self.assertEqual(msg["payload"], {"x": 1.0, "y": 0.0, "text": "가" * 200, "color": "#ff3b30", "size": 0.15})
            # 빈 글자는 무시, 정상 값은 그대로
            tw.send_json({"type": "TEXT", "payload": {"x": .5, "y": .5, "text": "   "}})
            tw.send_json({"type": "TEXT", "payload": {"x": .25, "y": .5, "text": "안녕", "color": "#00ff00", "size": .05}})
            msg = sw.receive_json()
            self.assertEqual(msg["payload"], {"x": .25, "y": .5, "text": "안녕", "color": "#00ff00", "size": .05})

    def test_dm_and_chatlog(self):
        recorder.CHATLOG_DIR = Path(tempfile.mkdtemp())
        t, s1, s2 = login("teacher", "teacher"), login("kim"), login("lee")
        with client.websocket_connect(f"/ws/dm1?token={t}") as tw, \
             client.websocket_connect(f"/ws/dm1?token={s1}") as s1w, \
             client.websocket_connect(f"/ws/dm1?token={s2}") as s2w:
            # 입장 순서에 따라 쌓인 메시지를 모두 소비: MEMBERS/STATE는 join마다 전원/본인에게 발송됨
            for _ in range(4): tw.receive_json()
            for _ in range(3): s1w.receive_json()
            for _ in range(2): s2w.receive_json()

            # kim → teacher 귓속말: 두 사람만 수신
            s1w.send_json({"type": "DM", "payload": {"to": "teacher", "text": "몰래 질문"}})
            dm = tw.receive_json()
            self.assertEqual(dm["type"], "DM")
            self.assertEqual(dm["payload"], {"from": "kim", "to": "teacher", "text": "몰래 질문"})
            self.assertEqual(s1w.receive_json()["type"], "DM")  # 발신자 에코
            # 없는 상대 → 오류
            s1w.send_json({"type": "DM", "payload": {"to": "nobody", "text": "?"}})
            self.assertEqual(s1w.receive_json()["type"], "ERROR")

        self.assertEqual(client.get(f"/api/chatlog/dm1?token={t}").status_code, 200)
        self.assertEqual(client.get(f"/api/chatlog/dm1?token={s1}").status_code, 403)
        lines = [json.loads(l) for l in client.get(f"/api/chatlog/dm1?token={t}").text.strip().split("\n")]
        self.assertEqual(lines[0]["name"], "kim")
        self.assertEqual(lines[0]["to"], "teacher")

    def test_survey(self):
        t, s1, s2 = login("teacher", "teacher"), login("kim"), login("lee")
        with client.websocket_connect(f"/ws/sv1?token={t}") as tw, \
             client.websocket_connect(f"/ws/sv1?token={s1}") as s1w, \
             client.websocket_connect(f"/ws/sv1?token={s2}") as s2w:
            for _ in range(4): tw.receive_json()
            for _ in range(3): s1w.receive_json()
            for _ in range(2): s2w.receive_json()

            # 학생은 설문 발행 불가
            s1w.send_json({"type": "SURVEY_START", "payload": {"question": "?", "options": ["A", "B"]}})
            self.assertEqual(s1w.receive_json()["type"], "ERROR")

            # 익명 설문: 전원 SURVEY_START 수신, 투표 시 전원 집계 수신, 명단은 비공개
            tw.send_json({"type": "SURVEY_START", "payload": {"question": "점심?", "options": ["한식", "중식"], "anonymous": True}})
            for w in (tw, s1w, s2w):
                msg = w.receive_json()
                self.assertEqual(msg["type"], "SURVEY_START")
                self.assertEqual(msg["payload"]["options"], ["한식", "중식"])
            s1w.send_json({"type": "SURVEY_ANSWER", "payload": {"choice": 0}})
            for w in (tw, s1w, s2w):
                self.assertEqual(w.receive_json()["payload"]["tally"], [1, 0])
            tw.send_json({"type": "SURVEY_END"})
            for w in (tw, s1w, s2w):
                self.assertEqual(w.receive_json()["payload"]["tally"], [1, 0])

            # 실명 설문: 투표 명단은 강사에게만
            tw.send_json({"type": "SURVEY_START", "payload": {"question": "?", "options": ["O", "X"], "anonymous": False}})
            for w in (tw, s1w, s2w): w.receive_json()
            s1w.send_json({"type": "SURVEY_ANSWER", "payload": {"choice": 1}})
            self.assertEqual(tw.receive_json()["type"], "SURVEY_RESULT")
            voters = tw.receive_json()
            self.assertEqual(voters["type"], "SURVEY_VOTERS")
            self.assertEqual(voters["payload"]["votes"], {"kim": 1})
            s1w.receive_json(); s2w.receive_json()  # SURVEY_RESULT만 수신

    def test_admin_and_chat_history(self):
        recorder.CHATLOG_DIR = Path(tempfile.mkdtemp())  # 이전 실행의 실제 채팅 로그가 섞이지 않도록
        admin = login("admin", "admin")
        self.assertEqual(client.post("/api/login", json={"name": "admin", "password": "x"}).status_code, 401)
        with client.websocket_connect(f"/ws/h1?token={admin}") as aw:
            aw.receive_json(); aw.receive_json()  # MEMBERS, STATE
            aw.send_json({"type": "DRAW", "payload": {"x": 0}})  # 관리자도 판서 가능
            self.assertEqual(aw.receive_json()["type"], "DRAW")
            aw.send_json({"type": "CHAT", "payload": {"text": "이전 대화"}})
            self.assertEqual(aw.receive_json()["type"], "CHAT")

        s1, s2 = login("kim"), login("lee")
        with client.websocket_connect(f"/ws/h1?token={s1}") as s1w:
            s1w.receive_json()  # MEMBERS
            state = s1w.receive_json()
            self.assertEqual(state["type"], "STATE")
            self.assertEqual(state["payload"]["chat"], [{"name": "admin", "text": "이전 대화"}])
            # DM은 당사자 기록에만 남음
            s1w.send_json({"type": "DM", "payload": {"to": "ghost", "text": "x"}})
            s1w.receive_json()  # ERROR (상대 없음)
        with client.websocket_connect(f"/ws/h1?token={s1}") as s1w, \
             client.websocket_connect(f"/ws/h1?token={s2}") as s2w:
            s1w.receive_json(); s2w.receive_json()
            s1w.send_json({"type": "DM", "payload": {"to": "kim", "text": "나에게DM"}})
            s1w.receive_json()
        with client.websocket_connect(f"/ws/h1?token={s2}") as s2w:
            s2w.receive_json()
            state = s2w.receive_json()
            self.assertNotIn("나에게DM", str(state["payload"]["chat"]))

    def test_chat_file_upload(self):
        recorder.CHATLOG_DIR = Path(tempfile.mkdtemp())
        recorder.UPLOAD_DIR = Path(tempfile.mkdtemp())
        s1, s2 = login("kim"), login("lee")
        up = lambda tok, name, data, room="u1": client.post(f"/api/upload/{room}", params={"token": tok, "name": name}, content=data)
        with client.websocket_connect(f"/ws/u1?token={s1}") as w1, client.websocket_connect(f"/ws/u1?token={s2}") as w2:
            for _ in range(3): w1.receive_json()
            for _ in range(2): w2.receive_json()
            r = up(s1, "../수업 자료.pdf", b"%PDF-1.4 hello")
            self.assertEqual(r.status_code, 200)
            f = r.json()
            self.assertEqual((f["name"], f["size"]), ("수업 자료.pdf", 14))  # 경로는 제거되고 한글 이름은 유지
            for w in (w1, w2):
                m = w.receive_json()
                self.assertEqual(m["type"], "CHAT")
                self.assertEqual(m["payload"]["file"], f)
                self.assertEqual(m["payload"]["name"], "kim")
            # 내려받기: 토큰 필요, 항상 attachment, 내용 동일
            url = f"/api/files/u1/{f['id']}/{f['name']}"
            self.assertEqual(client.get(url).status_code, 401)
            d = client.get(url, params={"token": s2})
            self.assertEqual(d.content, b"%PDF-1.4 hello")
            self.assertIn("attachment", d.headers["content-disposition"])
            self.assertEqual(d.headers["x-content-type-options"], "nosniff")
            # 이미지가 아니면 inline을 요청해도 내려받기로 처리
            self.assertIn("attachment", client.get(url, params={"token": s2, "inline": 1}).headers["content-disposition"])
            # 거절: 실행 파일, 빈 파일, 입장하지 않은 방, 토큰 없음, 용량 초과, 잘못된 경로
            self.assertEqual(up(s1, "a.exe", b"x").status_code, 400)
            self.assertEqual(up(s1, "a.txt", b"").status_code, 400)
            self.assertEqual(up(s1, "a.txt", b"x", room="other").status_code, 403)
            self.assertEqual(up("bad", "a.txt", b"x").status_code, 401)
            self.assertEqual(up(s1, "big.bin", b"0" * (20 * 1024 * 1024 + 1)).status_code, 413)
            self.assertEqual(client.get(f"/api/files/u1/{f['id']}/..%2Fx", params={"token": s1}).status_code, 404)
            self.assertEqual(client.get("/api/files/u1/zzzzzzzzzzzz/a.txt", params={"token": s1}).status_code, 404)
            # 이미지는 inline 미리보기 허용
            img = up(s1, "p.png", b"\x89PNG").json()
            r = client.get(f"/api/files/u1/{img['id']}/p.png", params={"token": s1, "inline": 1})
            self.assertEqual(r.headers["content-type"], "image/png")
            self.assertNotIn("attachment", r.headers.get("content-disposition", ""))  # 화면에 직접 표시
        # 다시 입장하면 기록에 파일 정보가 남아 있다(서버 재시작 후에도 로그에서 복원)
        with client.websocket_connect(f"/ws/u1?token={s2}") as w2:
            w2.receive_json()
            chat = w2.receive_json()["payload"]["chat"]
            self.assertEqual([c["file"]["name"] for c in chat if c.get("file")], ["수업 자료.pdf", "p.png"])

    def test_login_kinds(self):
        post = lambda **b: client.post("/api/login", json=b)
        # 수강생 탭: 강의자 아이디는 쓸 수 없고, 일반 이름은 수강생
        r = post(name="teacher", password="teacher", kind="student")
        self.assertEqual(r.status_code, 401)
        self.assertIn("강의자 탭", r.json()["detail"])
        self.assertEqual(post(name="kim", kind="student").json()["role"], "student")
        # 강의자 탭: 계정 + 비밀번호만 허용(없는 아이디로는 수강생이 될 수 없다)
        self.assertEqual(post(name="teacher", password="teacher", kind="staff").json()["role"], "teacher")
        self.assertEqual(post(name="teacher", password="x", kind="staff").status_code, 401)
        self.assertEqual(post(name="kim", kind="staff").status_code, 401)
        self.assertEqual(post(name="admin", password="admin", kind="staff").json()["role"], "admin")

    def test_student_screen_share(self):
        t, s1, s2 = login("teacher", "teacher"), login("kim"), login("lee")
        mt = lambda token, path, action="publish": client.post(
            "/api/mediamtx/auth", json={"action": action, "path": path, "password": token}).status_code
        with client.websocket_connect(f"/ws/sh1?token={t}") as tw, client.websocket_connect(f"/ws/sh1?token={s1}") as w1, \
             client.websocket_connect(f"/ws/sh1?token={s2}") as w2:
            for _ in range(4): tw.receive_json()  # MEMBERS, STATE, 그리고 두 수강생 입장 때의 MEMBERS
            for _ in range(3): w1.receive_json()  # MEMBERS, STATE, w2 입장 때의 MEMBERS
            for _ in range(2): w2.receive_json()
            # 허용 전에는 수강생이 공유 영상을 올릴 수 없다
            self.assertEqual(mt(s1, "sh1__share"), 403)
            w1.send_json({"type": "SHARE_REQUEST", "payload": {}})
            st = tw.receive_json()
            self.assertEqual(st["type"], "SHARE_STATE")
            self.assertEqual(st["payload"], {"presenter": None, "requests": ["kim"], "requested": False})
            own = w1.receive_json()["payload"]
            self.assertEqual((own["requests"], own["requested"]), ([], True))  # 수강생은 자기 요청 여부만 안다
            w2.receive_json()
            # 수강생은 허용할 수 없다
            w2.send_json({"type": "SHARE_GRANT", "payload": {"name": "kim"}})
            self.assertEqual(w2.receive_json()["type"], "ERROR")
            # 요청하지 않은 사람은 허용 불가, 요청한 사람은 허용
            tw.send_json({"type": "SHARE_GRANT", "payload": {"name": "lee"}})
            tw.send_json({"type": "SHARE_GRANT", "payload": {"name": "kim"}})
            st = tw.receive_json()
            self.assertEqual(st["payload"], {"presenter": "kim", "requests": [], "requested": False})
            w1.receive_json(); w2.receive_json()
            self.assertEqual(mt(s1, "sh1__share"), 200)   # 발표자만 올릴 수 있다
            self.assertEqual(mt(s2, "sh1__share"), 403)
            self.assertEqual(mt(t, "sh1__share"), 403)    # 강의자 영상은 원래 경로
            self.assertEqual(mt(t, "sh1"), 200)
            self.assertEqual(mt(s1, "sh1"), 403)          # 수강생은 강의 영상 경로에는 올릴 수 없다
            self.assertEqual(mt(s2, "sh1__share", "read"), 200)
            # 발표자가 끝내면 상태가 초기화된다
            w1.send_json({"type": "SHARE_END", "payload": {}})
            self.assertIsNone(tw.receive_json()["payload"]["presenter"])
            w1.receive_json(); w2.receive_json()
            self.assertEqual(mt(s1, "sh1__share"), 403)
            # 강의자가 중간에 중지시킬 수 있고, 발표자가 나가면 정리된다
            w2.send_json({"type": "SHARE_REQUEST", "payload": {}})
            for w in (tw, w1, w2): w.receive_json()
            tw.send_json({"type": "SHARE_GRANT", "payload": {"name": "lee"}})
            for w in (tw, w1, w2): w.receive_json()
            tw.send_json({"type": "SHARE_STOP", "payload": {}})
            for w in (tw, w1, w2): self.assertIsNone(w.receive_json()["payload"]["presenter"])

    def test_draw_modes_and_width(self):
        t = login("teacher", "teacher")
        with client.websocket_connect(f"/ws/dw1?token={t}") as tw:
            for _ in range(2): tw.receive_json()
            tw.send_json({"type": "DRAW", "payload": {"x": 2, "y": .5, "color": "#ffcc00", "isDragging": True, "mode": "highlight", "w": .035}})
            self.assertEqual(tw.receive_json()["payload"], {"x": 1.0, "y": .5, "color": "#ffcc00", "isDragging": True, "mode": "highlight", "w": .035})
            tw.send_json({"type": "DRAW", "payload": {"x": .1, "y": .1, "color": "red", "mode": "<b>", "w": 99}})  # 잘못된 값은 기본값/범위로
            self.assertEqual(tw.receive_json()["payload"], {"x": .1, "y": .1, "color": "#ff3b30", "isDragging": False, "mode": "pen", "w": 0.2})
            tw.send_json({"type": "DRAW", "payload": {"x": .3, "y": .3, "mode": "erase", "w": 0}})
            self.assertEqual(tw.receive_json()["payload"]["w"], 0.001)

    def test_shapes_and_icons(self):
        t, s = login("teacher", "teacher"), login("kim")
        with client.websocket_connect(f"/ws/sp1?token={t}") as tw, client.websocket_connect(f"/ws/sp1?token={s}") as sw:
            for _ in range(3): tw.receive_json()
            for _ in range(2): sw.receive_json()
            sw.send_json({"type": "SHAPE", "payload": {"kind": "rect", "x1": 0, "y1": 0, "x2": 1, "y2": 1}})
            self.assertEqual(sw.receive_json()["type"], "ERROR")  # 수강생은 불가
            tw.send_json({"type": "SHAPE", "payload": {"kind": "star-fish", "x1": 0}})  # 모르는 종류는 무시
            tw.send_json({"type": "ICON", "payload": {"icon": "<img>", "x": .5}})
            tw.send_json({"type": "SHAPE", "payload": {"kind": "arrow", "x1": -3, "y1": .2, "x2": 9, "y2": .8, "color": "red", "fill": "yes"}})
            m = sw.receive_json()
            self.assertEqual(m["type"], "SHAPE")
            self.assertEqual(m["payload"], {"kind": "arrow", "x1": 0.0, "y1": 0.2, "x2": 1.0, "y2": 0.8, "color": "#ff3b30", "fill": False, "w": 0.005})
            tw.receive_json()
            tw.send_json({"type": "ICON", "payload": {"icon": "star", "x": .3, "y": .4, "size": 5, "color": "#00ff00"}})
            self.assertEqual(sw.receive_json()["payload"], {"icon": "star", "x": .3, "y": .4, "size": 0.4, "color": "#00ff00"})

    def test_board_background(self):
        t, s = login("teacher", "teacher"), login("kim")
        with client.websocket_connect(f"/ws/bg1?token={t}") as tw, client.websocket_connect(f"/ws/bg1?token={s}") as sw:
            for _ in range(3): tw.receive_json()
            self.assertEqual(sw.receive_json()["type"], "MEMBERS")
            self.assertEqual(sw.receive_json()["payload"]["boardBg"], "video")
            tw.send_json({"type": "BOARD_BG", "payload": {"bg": "green"}})
            self.assertEqual(sw.receive_json()["payload"], {"bg": "green"})
            tw.receive_json()
            tw.send_json({"type": "BOARD_BG", "payload": {"bg": "<script>"}})  # 정해진 값만 허용(무시)
            sw.send_json({"type": "BOARD_BG", "payload": {"bg": "black"}})      # 수강생은 변경 불가
            self.assertEqual(sw.receive_json()["type"], "ERROR")
        with client.websocket_connect(f"/ws/bg1?token={s}") as sw:  # 늦게 입장해도 현재 배경을 받는다
            sw.receive_json()
            self.assertEqual(sw.receive_json()["payload"]["boardBg"], "green")

    def test_recording(self):
        recorder.RECORDINGS_DIR = Path(tempfile.mkdtemp())
        t, s = login("teacher", "teacher"), login("kim")
        with client.websocket_connect(f"/ws/rec1?token={t}") as tw, client.websocket_connect(f"/ws/rec1?token={s}") as sw:
            for _ in range(3): tw.receive_json()
            for _ in range(2): sw.receive_json()
            sw.send_json({"type": "REC_START"})
            self.assertEqual(sw.receive_json()["type"], "ERROR")
            tw.send_json({"type": "REC_START"})
            self.assertTrue(tw.receive_json()["payload"]["recording"]); sw.receive_json()
            tw.send_json({"type": "SNIPPET", "payload": {"text": "ls"}})
            tw.receive_json(); sw.receive_json()
            tw.send_json({"type": "REC_STOP"})
            self.assertFalse(tw.receive_json()["payload"]["recording"])
        files = client.get(f"/api/recordings?token={t}").json()
        self.assertEqual(len(files), 1)
        self.assertEqual(client.get(f"/api/recordings?token={s}").status_code, 403)
        body = client.get(f"/api/recordings/rec1/{files[0]['file']}?token={s}").text
        types = [json.loads(l)["type"] for l in body.strip().split("\n")]
        self.assertEqual(types, ["REC_START", "SNIPPET", "REC_STOP"])
        self.assertEqual(client.get(f"/api/recordings/..%2Fx/a.jsonl?token={s}").status_code, 404)

    def test_bad_token_rejected(self):
        with self.assertRaises(Exception):
            with client.websocket_connect("/ws/r1?token=bad"):
                pass


if __name__ == "__main__":
    unittest.main()
