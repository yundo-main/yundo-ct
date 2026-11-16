//! 방(Room) 단위 연결 관리와 강의 상태(퀴즈, 설문, 질문 큐, 채팅 기록).

use crate::recorder::Recorder;
use serde_json::{Map, Value, json};
use std::collections::VecDeque;
use tokio::sync::mpsc::UnboundedSender;

pub const CHAT_HISTORY_MAX: usize = 200;
/// 늦게 입장한 사람에게 다시 보내 줄 판서 메시지 최대 개수
pub const BOARD_MAX: usize = 30000;

pub struct Member {
    pub id: u64,
    pub tx: UnboundedSender<String>,
    pub name: String,
    pub role: String,
}

impl Member {
    pub fn send(&self, msg: &Value) -> bool {
        self.tx.send(msg.to_string()).is_ok()
    }
}

/// 퀴즈와 설문이 같이 쓰는 투표 상태. 설문만 `anonymous`를 가진다.
pub struct Poll {
    pub id: u64,
    pub question: String,
    pub options: Vec<String>,
    pub anonymous: Option<bool>,
    /// (이름, 선택 인덱스) — 입력 순서를 유지하고, 다시 투표하면 값만 바뀐다.
    pub votes: Vec<(String, usize)>,
}

impl Poll {
    /// 클라이언트에 보여 줄 정보(투표 내역 제외)
    pub fn public(&self) -> Value {
        let mut v = json!({"id": self.id, "question": self.question, "options": self.options});
        if let Some(a) = self.anonymous {
            v["anonymous"] = json!(a);
        }
        v
    }

    pub fn vote(&mut self, name: &str, choice: usize) {
        match self.votes.iter_mut().find(|(n, _)| n == name) {
            Some(entry) => entry.1 = choice,
            None => self.votes.push((name.to_string(), choice)),
        }
    }

    pub fn tally(&self) -> Vec<usize> {
        let mut counts = vec![0; self.options.len()];
        for (_, idx) in &self.votes {
            counts[*idx] += 1;
        }
        counts
    }

    pub fn voters(&self) -> Value {
        let mut m = Map::new();
        for (name, idx) in &self.votes {
            m.insert(name.clone(), json!(idx));
        }
        Value::Object(m)
    }
}

pub fn tally_of(poll: &Option<Poll>) -> Vec<usize> {
    poll.as_ref().map(Poll::tally).unwrap_or_default()
}

#[derive(Default)]
pub struct Room {
    pub members: Vec<Member>,
    pub quiz: Option<Poll>,
    pub survey: Option<Poll>,
    pub questions: Vec<Value>,
    pub recorder: Option<Recorder>,
    pub chat_history: VecDeque<Value>,
    /// 서버 재시작 후 첫 입장 때 chatlogs 파일에서 복원했는지
    pub chat_loaded: bool,
    /// 지금 화면을 공유 중인 수강생(강의자가 허용한 한 명)
    pub presenter: Option<String>,
    /// 판서 배경: video(영상 위) / white / green / black / grid. 비어 있으면 video.
    pub board_bg: String,
    /// 마지막 CLEAR 이후의 판서 메시지(DRAW/SHAPE/ICON/TEXT). 늦게 입장한 사람에게 재생해 준다.
    pub board: VecDeque<Value>,
    /// 화면 공유를 요청하고 기다리는 수강생
    pub share_requests: Vec<String>,
    qid: u64,
}

impl Room {
    pub fn next_qid(&mut self) -> u64 {
        self.qid += 1;
        self.qid
    }

    pub fn push_board(&mut self, item: Value) {
        self.board.push_back(item);
        while self.board.len() > BOARD_MAX {
            self.board.pop_front();
        }
    }

    pub fn push_chat(&mut self, item: Value) {
        self.chat_history.push_back(item);
        while self.chat_history.len() > CHAT_HISTORY_MAX {
            self.chat_history.pop_front();
        }
    }

    /// 방 전원(또는 `only_role` 역할만)에게 전송. 끊어진 연결은 목록에서 제거한다.
    pub fn broadcast(&mut self, msg: &Value, only_role: Option<&str>) {
        self.members.retain(|m| only_role.is_some_and(|r| m.role != r) || m.send(msg));
    }

    /// 화면 공유 상태. 대기 요청 목록은 강의자에게만 보낸다.
    pub fn share_state(&self, staff: bool, name: &str) -> Value {
        json!({
            "presenter": self.presenter,
            "requests": if staff { self.share_requests.clone() } else { vec![] },
            "requested": self.share_requests.iter().any(|n| n == name),
        })
    }

    pub fn broadcast_share(&mut self) {
        let msgs: Vec<Value> = self
            .members
            .iter()
            .map(|m| json!({"type": "SHARE_STATE", "payload": self.share_state(m.role == "teacher" || m.role == "admin", &m.name)}))
            .collect();
        let mut it = msgs.iter();
        self.members.retain(|m| it.next().is_some_and(|msg| m.send(msg)));
    }

    pub fn broadcast_members(&mut self) {
        let list: Vec<Value> =
            self.members.iter().map(|m| json!({"name": m.name, "role": m.role})).collect();
        self.broadcast(&json!({"type": "MEMBERS", "payload": {"members": list}}), None);
    }
}
