//! 강의도구 서버(Rust/axum): 인증 + MediaMTX 연동 + 실시간 강의 도구.
//! API·메시지 규약은 docs/server-api.md 를 따른다. (이전 파이썬 서버는 legacy/python-server/)

pub mod auth;
pub mod config;
pub mod recorder;
pub mod rooms;

use auth::Claims;
use axum::{
    Json, Router,
    body::Bytes,
    extract::{
        DefaultBodyLimit, Path, Query, State, WebSocketUpgrade,
        ws::{Message, WebSocket},
    },
    http::{StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use config::Config;
use futures_util::{SinkExt, StreamExt};
use recorder::Recorder;
use rooms::{Member, Poll, Room, tally_of};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
};
use tokio::sync::mpsc;

const INDEX_HTML: &str = include_str!("../../web/index.html");
const REPLAY_HTML: &str = include_str!("../../web/replay.html");

/// 판서 배경 종류(영상 위 / 흰색 / 칠판 초록 / 검정 / 모눈)
const BOARD_BGS: &[&str] = &["video", "white", "green", "black", "grid"];

/// 수강생 화면 공유 영상 경로: {방}__share
const SHARE_SUFFIX: &str = "__share";

/// 강사 전용 메시지 종류
const TEACHER_ONLY: &[&str] = &[
    "SHAPE", "ICON", "MOVE", "BOARD_BG", "SHARE_GRANT", "SHARE_DENY", "SHARE_STOP", "TEXT", "DRAW", "CLEAR", "SNIPPET", "QUIZ_START", "QUIZ_END", "QUESTION_DONE", "REC_START",
    "REC_STOP", "SURVEY_START", "SURVEY_END",
];

#[derive(Clone)]
pub struct AppState {
    cfg: Arc<Config>,
    rooms: Arc<Mutex<HashMap<String, Room>>>,
    next_id: Arc<AtomicU64>,
}

pub fn build_app(cfg: Config) -> Router {
    let state = AppState {
        cfg: Arc::new(cfg),
        rooms: Arc::default(),
        next_id: Arc::default(),
    };
    Router::new()
        .route("/", get(|| async { Html(INDEX_HTML) }))
        .route("/static/index.html", get(|| async { Html(INDEX_HTML) }))
        .route("/replay", get(|| async { Html(REPLAY_HTML) }))
        .route("/static/replay.html", get(|| async { Html(REPLAY_HTML) }))
        .route("/api/login", post(login))
        .route("/api/mediamtx/auth", post(mediamtx_auth))
        .route("/api/recordings", get(recordings))
        .route("/api/recordings/{room_id}/{file}", get(recording_events))
        .route("/api/chatlog/{room_id}", get(chatlog))
        .route("/api/polls/{room_id}", get(polls))
        .route("/api/upload/{room_id}", post(upload).layer(DefaultBodyLimit::max(MAX_UPLOAD)))
        .route("/api/files/{room_id}/{file_id}/{name}", get(download))
        .route("/ws/{room_id}", get(ws_upgrade))
        .with_state(state)
}

// ---------- HTTP API ----------

fn api_err(code: StatusCode, msg: &str) -> Response {
    (code, Json(json!({ "detail": msg }))).into_response()
}

fn ndjson(text: String) -> Response {
    ([(header::CONTENT_TYPE, "application/x-ndjson")], text).into_response()
}

#[derive(Deserialize)]
struct TokenQuery {
    #[serde(default)]
    token: String,
}

#[derive(Deserialize)]
struct LoginBody {
    name: String,
    #[serde(default)]
    password: String,
    #[serde(default)]
    kind: String,
}

async fn login(State(st): State<AppState>, Json(body): Json<LoginBody>) -> Response {
    let kind = if body.kind == "student" || body.kind == "staff" { body.kind.as_str() } else { "auto" };
    match auth::login(&st.cfg, &body.name, &body.password, kind) {
        Some(token) => {
            let role = auth::verify_token(&st.cfg, &token).map(|c| c.role).unwrap_or_default();
            Json(json!({ "token": token, "role": role })).into_response()
        }
        None if kind == "student" && st.cfg.users.iter().any(|(n, _, _)| *n == body.name) => api_err(
            StatusCode::UNAUTHORIZED,
            "강의자 아이디는 수강생 이름으로 쓸 수 없습니다. 강의자 탭에서 입장하세요.",
        ),
        None if kind == "staff" => api_err(StatusCode::UNAUTHORIZED, "강의자 아이디 또는 비밀번호가 올바르지 않습니다."),
        None => api_err(StatusCode::UNAUTHORIZED, "이름 또는 비밀번호가 올바르지 않습니다."),
    }
}

/// MediaMTX externalAuthenticationURL 요청 본문(일부). 모르는 필드는 무시한다.
#[derive(Deserialize, Default)]
#[serde(default)]
struct MediaMtxAuth {
    password: String,
    token: String,
    action: String,
    query: String,
    path: String,
}

/// publish는 강사/관리자만, read는 로그인한 누구나. 토큰은 token/password/query(token=)로 전달.
async fn mediamtx_auth(State(st): State<AppState>, Json(req): Json<MediaMtxAuth>) -> Response {
    let mut token = if req.token.is_empty() { req.password.clone() } else { req.token.clone() };
    if token.is_empty() {
        if let Some((_, rest)) = req.query.split_once("token=") {
            token = rest.split('&').next().unwrap_or("").to_string();
        }
    }
    let Some(claims) = auth::verify_token(&st.cfg, &token) else {
        return api_err(StatusCode::UNAUTHORIZED, "Unauthorized");
    };
    if req.action == "publish" {
        let path = req.path.trim_start_matches('/');
        let allowed = if let Some(room) = path.strip_suffix(SHARE_SUFFIX) {
            // 수강생 화면 공유 경로: 강의자가 허용해서 지금 발표자인 그 수강생만 올릴 수 있다
            !claims.is_staff()
                && lock(&st).get(room).is_some_and(|r| r.presenter.as_deref() == Some(claims.name.as_str()))
        } else {
            claims.is_staff()
        };
        if !allowed {
            return api_err(StatusCode::FORBIDDEN, "Forbidden");
        }
    }
    Json(json!({})).into_response()
}

fn require_staff(st: &AppState, token: &str) -> Result<Claims, Response> {
    auth::verify_token(&st.cfg, token)
        .filter(Claims::is_staff)
        .ok_or_else(|| api_err(StatusCode::FORBIDDEN, "강사만 접근할 수 있습니다."))
}

async fn recordings(State(st): State<AppState>, Query(q): Query<TokenQuery>) -> Response {
    if let Err(r) = require_staff(&st, &q.token) {
        return r;
    }
    Json(recorder::list_recordings(&st.cfg.recordings_dir)).into_response()
}

/// 다시보기용 이벤트 로그. 로그인한 사람이면 볼 수 있다.
async fn recording_events(
    State(st): State<AppState>,
    Path((room_id, file)): Path<(String, String)>,
    Query(q): Query<TokenQuery>,
) -> Response {
    if auth::verify_token(&st.cfg, &q.token).is_none() {
        return api_err(StatusCode::UNAUTHORIZED, "Unauthorized");
    }
    read_text_or_404(recorder::read_recording(&st.cfg.recordings_dir, &room_id, &file))
}

/// 방 채팅 로그. 강사만 조회 가능.
async fn chatlog(
    State(st): State<AppState>,
    Path(room_id): Path<String>,
    Query(q): Query<TokenQuery>,
) -> Response {
    if let Err(r) = require_staff(&st, &q.token) {
        return r;
    }
    read_text_or_404(recorder::read_chatlog(&st.cfg.chatlog_dir, &room_id))
}

/// 끝난 퀴즈·설문 결과(JSONL). 강의자만.
async fn polls(State(st): State<AppState>, Path(room_id): Path<String>, Query(q): Query<TokenQuery>) -> Response {
    if let Err(r) = require_staff(&st, &q.token) {
        return r;
    }
    read_text_or_404(recorder::read_polls(&st.cfg.chatlog_dir, &room_id))
}

// ---------- 채팅 첨부 파일 ----------

const MAX_UPLOAD: usize = 20 * 1024 * 1024; // 20MB
const BLOCKED_EXT: &[&str] = &["exe", "bat", "cmd", "com", "scr", "msi", "ps1", "vbs", "jar", "app", "dmg", "sh"];
const INLINE_EXT: &[(&str, &str)] =
    &[("png", "image/png"), ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("gif", "image/gif"), ("webp", "image/webp")];

/// 경로 구분자·제어문자·특수문자를 없애 안전한 파일 이름으로 만든다(100자). 파이썬 서버와 같은 규칙.
pub fn clean_filename(name: &str) -> String {
    let base = name.rsplit(['/', '\\']).next().unwrap_or("");
    let cleaned: String =
        base.chars().filter(|c| !c.is_control()).map(|c| if ":*?\"<>|".contains(c) { '_' } else { c }).collect();
    let trim = |s: &str| s.trim_matches(|c| c == ' ' || c == '.').to_string();
    let cut: String = trim(&cleaned).chars().take(100).collect();
    let cut = trim(&cut);
    if cut.is_empty() { "file".into() } else { cut }
}

fn ext_of(name: &str) -> String {
    name.rsplit_once('.').map(|(_, e)| e.to_lowercase()).unwrap_or_default()
}

#[derive(Deserialize)]
struct UploadQuery {
    #[serde(default)]
    token: String,
    #[serde(default)]
    name: String,
}

/// 본문은 파일 바이트 그대로. 올리면 방 전원에게 CHAT(file 포함)으로 알린다.
async fn upload(
    State(st): State<AppState>,
    Path(room_id): Path<String>,
    Query(q): Query<UploadQuery>,
    body: Bytes,
) -> Response {
    let Some(claims) = auth::verify_token(&st.cfg, &q.token) else {
        return api_err(StatusCode::UNAUTHORIZED, "Unauthorized");
    };
    let Some(room_dir) = recorder::safe_room(&room_id) else {
        return api_err(StatusCode::BAD_REQUEST, "올릴 수 없는 방 이름입니다.");
    };
    if !lock(&st).get(&room_id).is_some_and(|r| r.members.iter().any(|m| m.name == claims.name)) {
        return api_err(StatusCode::FORBIDDEN, "방에 입장한 사람만 올릴 수 있습니다.");
    }
    let fname = clean_filename(if q.name.is_empty() { "file" } else { &q.name });
    if fname.contains('.') && BLOCKED_EXT.contains(&ext_of(&fname).as_str()) {
        return api_err(StatusCode::BAD_REQUEST, "이 형식의 파일은 올릴 수 없습니다.");
    }
    if body.is_empty() {
        return api_err(StatusCode::BAD_REQUEST, "빈 파일입니다.");
    }
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    let seq = st.next_id.fetch_add(1, Ordering::Relaxed);
    let fid = format!("{:012x}", (nanos.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ seq) & 0xffff_ffff_ffff);
    let folder = st.cfg.upload_dir.join(room_dir).join(&fid);
    if tokio::fs::create_dir_all(&folder).await.is_err() || tokio::fs::write(folder.join(&fname), &body).await.is_err() {
        return api_err(StatusCode::INTERNAL_SERVER_ERROR, "파일을 저장하지 못했습니다.");
    }
    let file = json!({"id": fid, "name": fname, "size": body.len()});
    let payload = json!({"name": claims.name, "text": "", "file": file});
    {
        let mut rooms = lock(&st);
        if let Some(room) = rooms.get_mut(&room_id) {
            room.push_chat(payload.clone());
            room.broadcast(&json!({"type": "CHAT", "payload": payload}), None);
            if let Some(rec) = room.recorder.as_mut() {
                rec.write("CHAT", &payload, &claims.name);
            }
        }
    }
    recorder::log_chat(&st.cfg.chatlog_dir, &room_id, &claims.name, "", None, Some(&file));
    Json(file).into_response()
}

#[derive(Deserialize)]
struct DownloadQuery {
    #[serde(default)]
    token: String,
    #[serde(default)]
    inline: u8,
}

fn percent_encode(s: &str) -> String {
    s.bytes()
        .map(|b| if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") })
        .collect()
}

async fn download(
    State(st): State<AppState>,
    Path((room_id, file_id, name)): Path<(String, String, String)>,
    Query(q): Query<DownloadQuery>,
) -> Response {
    if auth::verify_token(&st.cfg, &q.token).is_none() {
        return api_err(StatusCode::UNAUTHORIZED, "Unauthorized");
    }
    let valid_id = file_id.len() == 12 && file_id.chars().all(|c| matches!(c, '0'..='9' | 'a'..='f'));
    let Some(room_dir) = recorder::safe_room(&room_id).filter(|_| valid_id && clean_filename(&name) == name) else {
        return api_err(StatusCode::NOT_FOUND, "Not Found");
    };
    let Ok(bytes) = tokio::fs::read(st.cfg.upload_dir.join(room_dir).join(&file_id).join(&name)).await else {
        return api_err(StatusCode::NOT_FOUND, "Not Found");
    };
    let ext = ext_of(&name);
    // 이미지 미리보기만 화면에 직접 표시하고, 나머지는 항상 내려받기로 처리한다
    let inline_type = INLINE_EXT.iter().find(|(e, _)| *e == ext).map(|(_, t)| *t).filter(|_| q.inline != 0);
    let (ctype, disp) = match inline_type {
        Some(t) => (t, "inline".to_string()),
        None => ("application/octet-stream", format!("attachment; filename=\"download\"; filename*=UTF-8''{}", percent_encode(&name))),
    };
    (
        [(header::CONTENT_TYPE, ctype.to_string()), (header::CONTENT_DISPOSITION, disp), (header::X_CONTENT_TYPE_OPTIONS, "nosniff".to_string())],
        bytes,
    )
        .into_response()
}

fn read_text_or_404(path: Option<std::path::PathBuf>) -> Response {
    match path.and_then(|p| std::fs::read_to_string(p).ok()) {
        Some(text) => ndjson(text),
        None => api_err(StatusCode::NOT_FOUND, "Not Found"),
    }
}

// ---------- WebSocket ----------

async fn ws_upgrade(
    ws: WebSocketUpgrade,
    State(st): State<AppState>,
    Path(room_id): Path<String>,
    Query(q): Query<TokenQuery>,
) -> Response {
    // 토큰이 잘못되면 연결 자체를 거절한다.
    let Some(claims) = auth::verify_token(&st.cfg, &q.token) else {
        return StatusCode::FORBIDDEN.into_response();
    };
    ws.on_upgrade(move |socket| run_socket(st, room_id, claims, socket))
}

/// 메시지를 보낸 사람 정보
struct Me {
    name: String,
    role: String,
    tx: mpsc::UnboundedSender<String>,
}

impl Me {
    fn send(&self, msg: Value) {
        let _ = self.tx.send(msg.to_string());
    }
    fn error(&self, message: &str) {
        self.send(json!({"type": "ERROR", "payload": {"message": message}}));
    }
}

async fn run_socket(st: AppState, room_id: String, claims: Claims, socket: WebSocket) {
    let (mut sink, mut stream) = socket.split();
    let (tx, mut rx) = mpsc::unbounded_channel::<String>();
    // 쓰기 전용 태스크: 방에서 온 메시지를 이 연결로 내보낸다.
    tokio::spawn(async move {
        while let Some(text) = rx.recv().await {
            if sink.send(Message::Text(text.into())).await.is_err() {
                break;
            }
        }
    });

    let id = st.next_id.fetch_add(1, Ordering::Relaxed);
    let me = Me { name: claims.name.clone(), role: claims.role.clone(), tx: tx.clone() };
    join_room(&st, &room_id, id, &me);

    while let Some(Ok(frame)) = stream.next().await {
        match frame {
            Message::Text(text) => {
                if let Ok(msg) = serde_json::from_str::<Value>(&text) {
                    handle(&st, &room_id, &me, msg);
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }
    leave_room(&st, &room_id, id);
}

fn lock(st: &AppState) -> std::sync::MutexGuard<'_, HashMap<String, Room>> {
    st.rooms.lock().unwrap_or_else(|e| e.into_inner())
}

fn join_room(st: &AppState, room_id: &str, id: u64, me: &Me) {
    let mut rooms = lock(st);
    let room = rooms.entry(room_id.to_string()).or_default();
    room.members.push(Member { id, tx: me.tx.clone(), name: me.name.clone(), role: me.role.clone() });

    // 서버 재시작 후 첫 입장이면 채팅 기록 복원(최근 200줄)
    if !room.chat_loaded {
        room.chat_loaded = true;
        if let Some(text) = recorder::read_chatlog(&st.cfg.chatlog_dir, room_id)
            .and_then(|p| std::fs::read_to_string(p).ok())
        {
            let lines: Vec<&str> = text.trim().split('\n').collect();
            for line in &lines[lines.len().saturating_sub(rooms::CHAT_HISTORY_MAX)..] {
                if let Ok(item) = serde_json::from_str::<Value>(line) {
                    let mut entry = json!({
                        "name": item["name"], "text": item["text"],
                        "to": item.get("to").cloned().unwrap_or(json!("")),
                    });
                    if let Some(file) = item.get("file").filter(|f| !f.is_null()) {
                        entry["file"] = file.clone();
                    }
                    room.push_chat(entry);
                }
            }
        }
    }
    room.broadcast_members();

    // 늦게 입장한 사람에게 현재 상태 전달
    let chat: Vec<&Value> = room
        .chat_history
        .iter()
        .filter(|c| {
            let to = c.get("to").and_then(Value::as_str).unwrap_or("");
            to.is_empty() || to == me.name || c["name"] == json!(me.name)
        })
        .collect();
    me.send(json!({"type": "STATE", "payload": {
        "role": me.role,
        "quiz": room.quiz.as_ref().map(|q| q.public()),
        "tally": tally_of(&room.quiz),
        "survey": room.survey.as_ref().map(|s| s.public()),
        "surveyTally": tally_of(&room.survey),
        "questions": room.questions,
        "recording": room.recorder.is_some(),
        "share": room.share_state(auth::is_staff(&me.role), &me.name),
        "boardBg": if room.board_bg.is_empty() { "video" } else { room.board_bg.as_str() },
        "board": room.board,
        "chat": chat,
    }}));
}

fn leave_room(st: &AppState, room_id: &str, id: u64) {
    let mut rooms = lock(st);
    let Some(room) = rooms.get_mut(room_id) else { return };
    let left = room.members.iter().find(|m| m.id == id).map(|m| m.name.clone());
    room.members.retain(|m| m.id != id);
    room.broadcast_members();
    // 공유 중이거나 요청 중이던 수강생이 완전히 나가면 정리한다
    if let Some(name) = left.filter(|n| !room.members.iter().any(|m| m.name == *n)) {
        let was_presenter = room.presenter.as_deref() == Some(name.as_str());
        let was_requesting = room.share_requests.contains(&name);
        if was_presenter {
            room.presenter = None;
        }
        room.share_requests.retain(|n| *n != name);
        if was_presenter || was_requesting {
            room.broadcast_share();
        }
    }
    // 강사가 모두 나가면 녹화 파일을 안전하게 닫는다
    if !room.members.iter().any(|m| m.role == "teacher") {
        if let Some(rec) = room.recorder.take() {
            rec.stop();
            room.broadcast(&json!({"type": "REC_STATE", "payload": {"recording": false}}), None);
        }
    }
}

// ---------- 메시지 처리 ----------

/// 파이썬의 `str(v)`에 해당: 문자열은 그대로, 그 밖의 값은 JSON 표기.
fn py_str(v: Option<&Value>) -> String {
    match v {
        None => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(other) => other.to_string(),
    }
}

fn trunc(s: String, max_chars: usize) -> String {
    if s.chars().count() <= max_chars { s } else { s.chars().take(max_chars).collect() }
}

fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64() != Some(0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// 판서 텍스트: 좌표·크기는 범위로 제한하고 색은 #rrggbb만 허용한다. 길이는 200자까지.
fn clean_text(p: &Value) -> Value {
    let num = |k: &str, default: f64, lo: f64, hi: f64| {
        p.get(k).and_then(Value::as_f64).map(|x| x.clamp(lo, hi)).unwrap_or(default)
    };
    let color = p.get("color").and_then(Value::as_str).filter(|c| {
        c.len() == 7 && c.starts_with('#') && c[1..].chars().all(|ch| ch.is_ascii_hexdigit())
    });
    json!({
        "x": num("x", 0.0, 0.0, 1.0),
        "y": num("y", 0.0, 0.0, 1.0),
        "text": trunc(py_str(p.get("text")), 200),
        "color": color.unwrap_or("#ff3b30"),
        "size": num("size", 0.032, 0.01, 0.15),
    })
}

const DRAW_MODES: &[&str] = &["pen", "dash", "highlight", "erase"]; // 실선 펜 / 점선 펜 / 형광펜 / 지우개

/// 판서 점: 좌표·굵기는 범위로 제한하고 색은 #rrggbb만, 종류는 정해진 값만 허용한다. 굵기 w는 화면 높이에 대한 비율.
fn clean_draw(p: &Value) -> Value {
    let mode = p.get("mode").and_then(Value::as_str).filter(|m| DRAW_MODES.contains(m)).unwrap_or("pen");
    json!({
        "x": num_of(p, "x", 0.0, 0.0, 1.0), "y": num_of(p, "y", 0.0, 0.0, 1.0),
        "color": color_of(p),
        "isDragging": p.get("isDragging") == Some(&json!(true)),
        "mode": mode,
        "w": num_of(p, "w", 0.005, 0.001, 0.2),
    })
}

const SHAPE_KINDS: &[&str] = &["line", "arrow", "rect", "ellipse"];
const ICON_NAMES: &[&str] = &["check", "x", "star", "question", "bang", "heart", "bulb", "arrow", "flag", "smile"];

fn color_of(p: &Value) -> &str {
    p.get("color")
        .and_then(Value::as_str)
        .filter(|c| c.len() == 7 && c.starts_with('#') && c[1..].chars().all(|ch| ch.is_ascii_hexdigit()))
        .unwrap_or("#ff3b30")
}

fn num_of(p: &Value, k: &str, default: f64, lo: f64, hi: f64) -> f64 {
    p.get(k).and_then(Value::as_f64).map(|x| x.clamp(lo, hi)).unwrap_or(default)
}

/// 도형: 종류는 정해진 값만, 좌표는 0~1로 제한한다. 잘못된 값이면 None.
fn clean_shape(p: &Value) -> Option<Value> {
    let kind = p.get("kind").and_then(Value::as_str).filter(|k| SHAPE_KINDS.contains(k))?;
    Some(json!({
        "kind": kind,
        "x1": num_of(p, "x1", 0.0, 0.0, 1.0), "y1": num_of(p, "y1", 0.0, 0.0, 1.0),
        "x2": num_of(p, "x2", 0.0, 0.0, 1.0), "y2": num_of(p, "y2", 0.0, 0.0, 1.0),
        "color": color_of(p),
        "fill": p.get("fill") == Some(&json!(true)),
        "w": num_of(p, "w", 0.005, 0.001, 0.2),
    }))
}

/// 아이콘: 이름은 정해진 값만, 위치·크기는 범위로 제한한다. 잘못된 값이면 None.
fn clean_icon(p: &Value) -> Option<Value> {
    let icon = p.get("icon").and_then(Value::as_str).filter(|k| ICON_NAMES.contains(k))?;
    Some(json!({
        "icon": icon,
        "x": num_of(p, "x", 0.5, 0.0, 1.0), "y": num_of(p, "y", 0.5, 0.0, 1.0),
        "size": num_of(p, "size", 0.08, 0.02, 0.4),
        "color": color_of(p),
    }))
}

/// 이동: 개체 번호와 이동량(화면 비율). 번호가 없거나 숫자가 아니면 None.
fn clean_move(p: &Value) -> Option<Value> {
    let oid = p.get("oid").and_then(Value::as_u64)?;
    Some(json!({"oid": oid, "dx": num_of(p, "dx", 0.0, -1.0, 1.0), "dy": num_of(p, "dy", 0.0, -1.0, 1.0)}))
}

/// 보관 중인 판서(board)에서 번호가 같은 개체를 dx, dy만큼 옮긴다. 늦게 입장한 사람도 옮겨진 위치로 받는다.
fn apply_move(board: &mut std::collections::VecDeque<Value>, oid: u64, dx: f64, dy: f64) {
    fn shift(pl: &mut Value, kx: &str, ky: &str, dx: f64, dy: f64) {
        if let Some(x) = pl[kx].as_f64() {
            pl[kx] = json!(x + dx);
        }
        if let Some(y) = pl[ky].as_f64() {
            pl[ky] = json!(y + dy);
        }
    }
    for item in board.iter_mut() {
        let ty = item["type"].as_str().unwrap_or("").to_string();
        let pl = &mut item["payload"];
        if pl["oid"].as_u64() != Some(oid) {
            continue;
        }
        match ty.as_str() {
            "TEXT" | "ICON" | "DRAW" => shift(pl, "x", "y", dx, dy),
            "SHAPE" => {
                shift(pl, "x1", "y1", dx, dy);
                shift(pl, "x2", "y2", dx, dy);
            }
            _ => {}
        }
    }
}

fn choice_in_range(p: &Value, option_count: usize) -> Option<usize> {
    let idx = p.get("choice")?.as_i64()?;
    (0 <= idx && (idx as usize) < option_count).then_some(idx as usize)
}

fn handle(st: &AppState, room_id: &str, me: &Me, msg: Value) {
    let t = msg.get("type").and_then(Value::as_str).unwrap_or("").to_string();
    let p = msg.get("payload").cloned().unwrap_or_else(|| json!({}));
    let t = t.as_str();

    if TEACHER_ONLY.contains(&t) && !auth::is_staff(&me.role) {
        me.error("강사만 사용할 수 있습니다.");
        return;
    }

    // 텍스트는 정리한 값만 전달·기록하고, 빈 글자는 무시한다
    let p = if t == "TEXT" { clean_text(&p) } else { p };
    if t == "TEXT" && p["text"].as_str().is_none_or(|s| s.trim().is_empty()) {
        return;
    }

    // 도형·아이콘은 정리한 값만 전달·기록한다
    let p = match t {
        "DRAW" => clean_draw(&p),
        "SHAPE" => match clean_shape(&p) {
            Some(v) => v,
            None => return,
        },
        "ICON" => match clean_icon(&p) {
            Some(v) => v,
            None => return,
        },
        "MOVE" => match clean_move(&p) {
            Some(v) => v,
            None => return,
        },
        _ => p,
    };

    // 배경은 정해진 값만 받는다
    let p = if t == "BOARD_BG" {
        let bg = p.get("bg").and_then(Value::as_str).unwrap_or("");
        if !BOARD_BGS.contains(&bg) {
            return;
        }
        json!({"bg": bg})
    } else {
        p
    };

    let mut rooms = lock(st);
    let room = rooms.entry(room_id.to_string()).or_default();

    match t {
        "REC_START" => {
            if room.recorder.is_none() {
                match Recorder::start(&st.cfg.recordings_dir, room_id) {
                    Some(r) => room.recorder = Some(r),
                    None => return me.error("녹화할 수 없는 방 이름입니다."),
                }
            }
            room.broadcast(&json!({"type": "REC_STATE", "payload": {"recording": true}}), None);
            return;
        }
        "REC_STOP" => {
            if let Some(rec) = room.recorder.take() {
                rec.stop();
            }
            room.broadcast(&json!({"type": "REC_STATE", "payload": {"recording": false}}), None);
            return;
        }
        _ => {}
    }

    // 판서 개체에 번호를 붙인다(이동할 때 이 번호로 가리킨다). 지우개 획은 이동 대상이 아니다.
    let mut p = p;
    match t {
        "TEXT" | "SHAPE" | "ICON" => p["oid"] = json!(room.next_oid()),
        "DRAW" => {
            if p["isDragging"] != json!(true) {
                room.stroke_oid = (p["mode"] != json!("erase")).then(|| room.next_oid());
            }
            if let Some(o) = room.stroke_oid {
                p["oid"] = json!(o);
            }
        }
        _ => {}
    }

    // 녹화 중이면 기록(스니펫은 전송되는 형태 그대로)
    if let Some(rec) = room.recorder.as_mut() {
        if t == "SNIPPET" {
            rec.write(t, &json!({"text": trunc(py_str(p.get("text")), 4000)}), &me.name);
        } else {
            rec.write(t, &p, &me.name);
        }
    }

    match t {
        "BOARD_BG" => {
            room.board_bg = py_str(p.get("bg"));
            room.broadcast(&json!({"type": t, "payload": p}), None);
        }
        "MOVE" => {
            apply_move(&mut room.board, p["oid"].as_u64().unwrap_or(0), p["dx"].as_f64().unwrap_or(0.0), p["dy"].as_f64().unwrap_or(0.0));
            room.broadcast(&json!({"type": t, "payload": p}), None);
        }
        "DRAW" | "CLEAR" | "TEXT" | "SHAPE" | "ICON" => {
            let msg = json!({"type": t, "payload": p});
            if t == "CLEAR" {
                room.board.clear();
                room.stroke_oid = None;
            } else {
                room.push_board(msg.clone());
            }
            room.broadcast(&msg, None);
        }
        "SNIPPET" => {
            let text = trunc(py_str(p.get("text")), 4000);
            room.broadcast(&json!({"type": t, "payload": {"text": text}}), None);
        }
        "QUIZ_START" => {
            let options: Vec<String> = match p.get("options").and_then(Value::as_array) {
                Some(a) => a.iter().map(|o| py_str(Some(o))).take(6).collect(),
                None => vec!["O".into(), "X".into()],
            };
            let quiz = Poll {
                id: room.questions.len() as u64 + 1000,
                question: py_str(p.get("question")),
                options,
                anonymous: None,
                votes: vec![],
            };
            let public = quiz.public();
            if let Some(old) = room.quiz.replace(quiz) {
                recorder::log_poll(&st.cfg.chatlog_dir, room_id, "quiz", &old); // 끝내지 않고 새로 발행해도 이전 결과를 남긴다
            }
            room.broadcast(&json!({"type": t, "payload": public}), None);
        }
        "QUIZ_ANSWER" => {
            if let Some(quiz) = room.quiz.as_mut() {
                if let Some(choice) = choice_in_range(&p, quiz.options.len()) {
                    quiz.vote(&me.name, choice);
                    let tally = quiz.tally();
                    room.broadcast(
                        &json!({"type": "QUIZ_RESULT", "payload": {"tally": tally}}),
                        Some("teacher"),
                    );
                }
            }
        }
        "QUIZ_END" => {
            if let Some(quiz) = room.quiz.take() {
                recorder::log_poll(&st.cfg.chatlog_dir, room_id, "quiz", &quiz);
                room.broadcast(&json!({"type": t, "payload": {"tally": quiz.tally()}}), None);
            }
        }
        "SURVEY_START" => {
            let options: Vec<String> = p
                .get("options")
                .and_then(Value::as_array)
                .map(|a| {
                    a.iter().map(|o| py_str(Some(o))).filter(|s| !s.trim().is_empty()).take(6).collect()
                })
                .unwrap_or_default();
            if options.is_empty() {
                return me.error("선택지가 필요합니다.");
            }
            let survey = Poll {
                id: room.next_qid(),
                question: py_str(p.get("question")),
                options,
                anonymous: Some(truthy(p.get("anonymous"))),
                votes: vec![],
            };
            let public = survey.public();
            if let Some(old) = room.survey.replace(survey) {
                recorder::log_poll(&st.cfg.chatlog_dir, room_id, "survey", &old);
            }
            room.broadcast(&json!({"type": t, "payload": public}), None);
        }
        "SURVEY_ANSWER" => {
            if let Some(survey) = room.survey.as_mut() {
                if let Some(choice) = choice_in_range(&p, survey.options.len()) {
                    survey.vote(&me.name, choice);
                    let (tally, voted) = (survey.tally(), survey.votes.len());
                    let voters = (survey.anonymous != Some(true)).then(|| survey.voters());
                    room.broadcast(
                        &json!({"type": "SURVEY_RESULT", "payload": {"tally": tally, "voted": voted}}),
                        None,
                    );
                    if let Some(votes) = voters {
                        room.broadcast(
                            &json!({"type": "SURVEY_VOTERS", "payload": {"votes": votes}}),
                            Some("teacher"),
                        );
                    }
                }
            }
        }
        "SURVEY_END" => {
            if let Some(survey) = room.survey.take() {
                recorder::log_poll(&st.cfg.chatlog_dir, room_id, "survey", &survey);
                room.broadcast(&json!({"type": t, "payload": {"tally": survey.tally()}}), None);
            }
        }
        "QUESTION" => {
            let q = json!({
                "id": room.next_qid(), "name": me.name,
                "text": trunc(py_str(p.get("text")), 500), "done": false,
            });
            room.questions.push(q.clone());
            room.broadcast(&json!({"type": t, "payload": q}), None);
        }
        "QUESTION_DONE" => {
            let id = p.get("id").cloned().unwrap_or(Value::Null);
            for q in room.questions.iter_mut().filter(|q| q["id"] == id) {
                q["done"] = json!(true);
            }
            room.broadcast(&json!({"type": t, "payload": {"id": id}}), None);
        }
        "CHAT" => {
            let text = trunc(py_str(p.get("text")), 500);
            room.push_chat(json!({"name": me.name, "text": text}));
            room.broadcast(&json!({"type": t, "payload": {"name": me.name, "text": text}}), None);
            recorder::log_chat(&st.cfg.chatlog_dir, room_id, &me.name, &text, None, None);
        }
        "DM" => {
            let target = py_str(p.get("to"));
            let text = trunc(py_str(p.get("text")), 500);
            let targets: Vec<&Member> = room.members.iter().filter(|m| m.name == target).collect();
            if targets.is_empty() {
                return me.error("상대를 찾을 수 없습니다.");
            }
            let dm = json!({"type": t, "payload": {"from": me.name, "to": target, "text": text}});
            for m in targets {
                m.send(&dm);
            }
            me.send(dm); // 발신자에게도 전달(에코)
            room.push_chat(json!({"name": me.name, "text": text, "to": target}));
            recorder::log_chat(&st.cfg.chatlog_dir, room_id, &me.name, &text, Some(&target), None);
        }
        "SHARE_REQUEST" => {
            if auth::is_staff(&me.role) || room.presenter.as_deref() == Some(me.name.as_str()) {
                return;
            }
            if !room.share_requests.contains(&me.name) {
                room.share_requests.push(me.name.clone());
            }
            room.broadcast_share();
        }
        "SHARE_CANCEL" => {
            if room.share_requests.contains(&me.name) {
                room.share_requests.retain(|n| *n != me.name);
                room.broadcast_share();
            }
        }
        "SHARE_GRANT" => {
            // 요청한 사람에게만 허용할 수 있다. 한 번에 한 명만 공유한다.
            let name = py_str(p.get("name"));
            if room.share_requests.contains(&name) {
                room.share_requests.retain(|n| *n != name);
                room.presenter = Some(name);
                room.broadcast_share();
            }
        }
        "SHARE_DENY" => {
            let name = py_str(p.get("name"));
            if room.share_requests.contains(&name) {
                room.share_requests.retain(|n| *n != name);
                room.broadcast_share();
            }
        }
        "SHARE_STOP" | "SHARE_END" => {
            if (t == "SHARE_STOP" || room.presenter.as_deref() == Some(me.name.as_str())) && room.presenter.is_some() {
                room.presenter = None;
                room.broadcast_share();
            }
        }
        "HAND" => {
            room.broadcast(&json!({"type": t, "payload": {"name": me.name}}), Some("teacher"));
        }
        _ => {}
    }
}
