"""방(Room) 단위 연결 관리와 강의 상태(퀴즈, 질문 큐)."""

import itertools
from collections import deque
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class Member:
    ws: WebSocket
    name: str
    role: str


@dataclass
class Room:
    members: list[Member] = field(default_factory=list)
    quiz: dict | None = None            # {"id", "question", "options", "answers": {name: idx}}
    survey: dict | None = None          # {"id", "question", "options", "anonymous", "votes": {name: idx}}
    questions: list[dict] = field(default_factory=list)
    recorder: object | None = None      # server.recorder.Recorder
    chat_history: deque = field(default_factory=lambda: deque(maxlen=200))
    chat_loaded: bool = False           # chatlogs 파일에서 복원했는지
    board_bg: str = "video"             # 판서 배경: video(영상 위) / white / green / black / grid
    presenter: str | None = None        # 지금 화면을 공유 중인 수강생 이름(강의자가 허용한 한 명)
    share_requests: list[str] = field(default_factory=list)  # 화면 공유를 요청하고 기다리는 수강생
    _qid: itertools.count = field(default_factory=lambda: itertools.count(1))

    def quiz_tally(self) -> list[int]:
        if not self.quiz:
            return []
        counts = [0] * len(self.quiz["options"])
        for idx in self.quiz["answers"].values():
            counts[idx] += 1
        return counts

    def survey_tally(self) -> list[int]:
        if not self.survey:
            return []
        counts = [0] * len(self.survey["options"])
        for idx in self.survey["votes"].values():
            counts[idx] += 1
        return counts


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def room(self, room_id: str) -> Room:
        return self.rooms.setdefault(room_id, Room())

    async def join(self, room_id: str, member: Member) -> Room:
        await member.ws.accept()
        room = self.room(room_id)
        room.members.append(member)
        return room

    def leave(self, room_id: str, member: Member) -> None:
        room = self.rooms.get(room_id)
        if room and member in room.members:
            room.members.remove(member)

    async def broadcast(self, room_id: str, message: dict, only_role: str | None = None) -> None:
        room = self.room(room_id)
        for m in list(room.members):
            if only_role and m.role != only_role:
                continue
            try:
                await m.ws.send_json(message)
            except Exception:
                self.leave(room_id, m)
