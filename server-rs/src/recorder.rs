//! 상호작용 이벤트 녹화(JSONL)와 채팅 로그. 파일 형식은 파이썬 서버와 같다.

use chrono::Local;
use serde_json::{Value, json};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub const RECORDED_TYPES: &[&str] = &[
    "SHAPE", "ICON", "BOARD_BG", "TEXT", "DRAW", "CLEAR", "SNIPPET", "QUIZ_START", "QUIZ_END", "QUESTION", "QUESTION_DONE", "CHAT",
    "SURVEY_START", "SURVEY_END",
];

/// 방 이름은 파일 경로에 쓰이므로 안전한 문자(영문·숫자·`-_`, 1~64자)만 허용한다.
pub fn safe_room(room_id: &str) -> Option<&str> {
    let ok = (1..=64).contains(&room_id.len())
        && room_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-');
    ok.then_some(room_id)
}

pub struct Recorder {
    file: File,
    t0: Instant,
}

impl Recorder {
    pub fn start(dir: &Path, room_id: &str) -> Option<Recorder> {
        let folder = dir.join(safe_room(room_id)?);
        fs::create_dir_all(&folder).ok()?;
        let now = Local::now();
        let path = folder.join(format!("{}.jsonl", now.format("%Y%m%d-%H%M%S")));
        let file = OpenOptions::new().create(true).append(true).open(path).ok()?;
        let mut r = Recorder { file, t0: Instant::now() };
        r.line(json!({"t": 0, "type": "REC_START", "wall": now.to_rfc3339()}));
        Some(r)
    }

    fn line(&mut self, obj: Value) {
        // 녹화 실패가 강의를 멈추면 안 되므로 쓰기 오류는 무시한다.
        let _ = writeln!(self.file, "{obj}");
        let _ = self.file.flush();
    }

    fn elapsed_ms(&self) -> u64 {
        self.t0.elapsed().as_millis() as u64
    }

    pub fn write(&mut self, type_: &str, payload: &Value, by: &str) {
        if RECORDED_TYPES.contains(&type_) {
            let t = self.elapsed_ms();
            self.line(json!({"t": t, "type": type_, "payload": payload, "by": by}));
        }
    }

    pub fn stop(mut self) {
        let t = self.elapsed_ms();
        self.line(json!({"t": t, "type": "REC_STOP"}));
    }
}

pub fn list_recordings(dir: &Path) -> Vec<Value> {
    let mut found: Vec<(String, String, u64)> = vec![];
    if let Ok(rooms) = fs::read_dir(dir) {
        for room in rooms.flatten() {
            let Ok(files) = fs::read_dir(room.path()) else { continue };
            for f in files.flatten() {
                let name = f.file_name().to_string_lossy().to_string();
                if name.ends_with(".jsonl") {
                    let size = f.metadata().map(|m| m.len()).unwrap_or(0);
                    found.push((room.file_name().to_string_lossy().to_string(), name, size));
                }
            }
        }
    }
    found.sort_by(|a, b| (&b.0, &b.1).cmp(&(&a.0, &a.1))); // 최신(경로 내림차순) 먼저
    found.into_iter().map(|(room, file, size)| json!({"room": room, "file": file, "size": size})).collect()
}

/// 다시보기용 이벤트 파일 경로. 이름 검증을 통과하고 실제로 있을 때만 돌려준다.
pub fn read_recording(dir: &Path, room_id: &str, file: &str) -> Option<PathBuf> {
    let stem = file.strip_suffix(".jsonl")?;
    if stem.is_empty() || !stem.chars().all(|c| c.is_ascii_digit() || c == '-') {
        return None;
    }
    let path = dir.join(safe_room(room_id)?).join(file);
    path.is_file().then_some(path)
}

/// 방별 채팅 로그(녹화와 무관하게 저장). DM은 `to`에 수신자 이름.
pub fn log_chat(dir: &Path, room_id: &str, name: &str, text: &str, to: Option<&str>, file: Option<&Value>) {
    let Some(room) = safe_room(room_id) else { return };
    let folder = dir.join(room);
    if fs::create_dir_all(&folder).is_err() {
        return;
    }
    let mut line = json!({"ts": Local::now().to_rfc3339(), "name": name, "text": text});
    if let Some(to) = to {
        line["to"] = json!(to);
    }
    if let Some(file) = file {
        line["file"] = file.clone();
    }
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(folder.join("chat.jsonl")) {
        let _ = writeln!(f, "{line}");
    }
}

/// 끝난 퀴즈·설문 한 건을 방별 `polls.jsonl`에 남긴다. 익명 설문은 사람별 선택을 저장하지 않는다.
pub fn log_poll(dir: &Path, room_id: &str, kind: &str, poll: &crate::rooms::Poll) {
    let Some(room) = safe_room(room_id) else { return };
    let folder = dir.join(room);
    if fs::create_dir_all(&folder).is_err() {
        return;
    }
    let mut line = json!({
        "ts": Local::now().to_rfc3339(), "kind": kind, "question": poll.question,
        "options": poll.options, "tally": poll.tally(), "voted": poll.votes.len(),
    });
    if poll.anonymous != Some(true) {
        line["votes"] = poll.voters();
    }
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(folder.join("polls.jsonl")) {
        let _ = writeln!(f, "{line}");
    }
}

pub fn read_polls(dir: &Path, room_id: &str) -> Option<PathBuf> {
    let path = dir.join(safe_room(room_id)?).join("polls.jsonl");
    path.is_file().then_some(path)
}

pub fn read_chatlog(dir: &Path, room_id: &str) -> Option<PathBuf> {
    let path = dir.join(safe_room(room_id)?).join("chat.jsonl");
    path.is_file().then_some(path)
}
