//! server/tests/test_server.py 의 시나리오를 그대로 옮긴 통합 테스트.
//! 각 테스트는 임시 폴더를 쓰는 서버를 임의 포트로 띄운다.

use futures_util::{SinkExt, StreamExt};
use lecture_server::{build_app, config::Config};
use serde_json::{Value, json};
use std::time::Duration;
use tempfile::TempDir;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream, connect_async, tungstenite::Message};

type Ws = WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>;

struct Server {
    addr: String,
    http: reqwest::Client,
    _dirs: (TempDir, TempDir, TempDir),
}

async fn start() -> Server {
    let (rec, chat, up) = (tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap(), tempfile::tempdir().unwrap());
    let mut cfg = Config::from_env();
    cfg.recordings_dir = rec.path().into();
    cfg.chatlog_dir = chat.path().into();
    cfg.upload_dir = up.path().into();
    cfg.secret = b"test-secret".to_vec();
    cfg.users = vec![
        ("teacher".into(), "teacher".into(), "teacher".into()),
        ("admin".into(), "admin".into(), "admin".into()),
    ];
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap().to_string();
    tokio::spawn(async move { axum::serve(listener, build_app(cfg)).await.unwrap() });
    Server { addr, http: reqwest::Client::new(), _dirs: (rec, chat, up) }
}

impl Server {
    fn url(&self, path: &str) -> String {
        format!("http://{}{path}", self.addr)
    }
    async fn post(&self, path: &str, body: Value) -> reqwest::Response {
        self.http.post(self.url(path)).json(&body).send().await.unwrap()
    }
    async fn get(&self, path: &str) -> reqwest::Response {
        self.http.get(self.url(path)).send().await.unwrap()
    }
    async fn login(&self, name: &str, password: &str) -> String {
        let r: Value = self.post("/api/login", json!({"name": name, "password": password})).await.json().await.unwrap();
        r["token"].as_str().unwrap().to_string()
    }
    async fn connect(&self, room: &str, token: &str) -> Ws {
        connect_async(format!("ws://{}/ws/{room}?token={token}", self.addr)).await.unwrap().0
    }
}

fn enc(s: &str) -> String {
    s.bytes().map(|b| if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) { (b as char).to_string() } else { format!("%{b:02X}") }).collect()
}

async fn recv(ws: &mut Ws) -> Value {
    let msg = tokio::time::timeout(Duration::from_secs(3), ws.next())
        .await
        .expect("3초 안에 메시지가 와야 한다")
        .expect("연결이 닫힘")
        .unwrap();
    serde_json::from_str(msg.to_text().unwrap()).unwrap()
}

async fn send(ws: &mut Ws, v: Value) {
    ws.send(Message::Text(v.to_string().into())).await.unwrap();
}

async fn drain(ws: &mut Ws, n: usize) {
    for _ in 0..n {
        recv(ws).await;
    }
}

#[tokio::test]
async fn login_rules() {
    let s = start().await;
    assert_eq!(s.post("/api/login", json!({"name": "teacher", "password": "x"})).await.status(), 401);
    assert_eq!(s.post("/api/login", json!({"name": "admin", "password": "x"})).await.status(), 401);
    assert_eq!(s.post("/api/login", json!({"name": "  "})).await.status(), 401);
    let r: Value = s.post("/api/login", json!({"name": "kim"})).await.json().await.unwrap();
    assert_eq!(r["role"], "student");
}

#[tokio::test]
async fn mediamtx_auth() {
    let s = start().await;
    let (t, st) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let code = |b: Value| async { s.post("/api/mediamtx/auth", b).await.status().as_u16() };
    assert_eq!(code(json!({"action": "publish", "password": t})).await, 200);
    assert_eq!(code(json!({"action": "publish", "password": st})).await, 403);
    assert_eq!(code(json!({"action": "read", "query": format!("token={st}")})).await, 200);
    assert_eq!(code(json!({"action": "read"})).await, 401);
}

#[tokio::test]
async fn realtime_flow() {
    let s = start().await;
    let (t, st) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let (mut tw, mut sw) = (s.connect("r1", &t).await, s.connect("r1", &st).await);
    // 입장 시 MEMBERS(전원)와 STATE(본인)가 발송됨
    drain(&mut tw, 3).await;
    drain(&mut sw, 2).await;
    send(&mut tw, json!({"type": "DRAW", "payload": {"x": 0.5, "y": 0.5}})).await;
    assert_eq!(recv(&mut sw).await["type"], "DRAW");
    recv(&mut tw).await; // 강사 본인에게도 브로드캐스트됨
    send(&mut sw, json!({"type": "DRAW", "payload": {}})).await;
    assert_eq!(recv(&mut sw).await["type"], "ERROR");
    send(&mut tw, json!({"type": "QUIZ_START", "payload": {"question": "?", "options": ["O", "X"]}})).await;
    recv(&mut tw).await;
    recv(&mut sw).await;
    send(&mut sw, json!({"type": "QUIZ_ANSWER", "payload": {"choice": 1}})).await;
    assert_eq!(recv(&mut tw).await["payload"]["tally"], json!([0, 1]));
    send(&mut sw, json!({"type": "CHAT", "payload": {"text": "안녕하세요"}})).await;
    for w in [&mut tw, &mut sw] {
        let m = recv(w).await;
        assert_eq!(m["type"], "CHAT");
        assert_eq!(m["payload"], json!({"name": "kim", "text": "안녕하세요"}));
    }
}

#[tokio::test]
async fn text_tool() {
    let s = start().await;
    let (t, st) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let (mut tw, mut sw) = (s.connect("tx1", &t).await, s.connect("tx1", &st).await);
    drain(&mut tw, 3).await;
    drain(&mut sw, 2).await;
    // 학생은 텍스트를 올릴 수 없다
    send(&mut sw, json!({"type": "TEXT", "payload": {"x": 0.1, "y": 0.1, "text": "x"}})).await;
    assert_eq!(recv(&mut sw).await["type"], "ERROR");
    // 값이 범위를 벗어나거나 이상해도 정리되어 전달된다
    let long = "가".repeat(300);
    send(&mut tw, json!({"type": "TEXT", "payload": {"x": 5, "y": -2, "text": long, "color": "red", "size": 9}})).await;
    let msg = recv(&mut sw).await;
    recv(&mut tw).await;
    assert_eq!(msg["type"], "TEXT");
    assert_eq!(msg["payload"], json!({"x": 1.0, "y": 0.0, "text": "가".repeat(200), "color": "#ff3b30", "size": 0.15}));
    // 빈 글자는 무시, 정상 값은 그대로
    send(&mut tw, json!({"type": "TEXT", "payload": {"x": 0.5, "y": 0.5, "text": "   "}})).await;
    send(&mut tw, json!({"type": "TEXT", "payload": {"x": 0.25, "y": 0.5, "text": "안녕", "color": "#00ff00", "size": 0.05}})).await;
    let msg = recv(&mut sw).await;
    assert_eq!(msg["payload"], json!({"x": 0.25, "y": 0.5, "text": "안녕", "color": "#00ff00", "size": 0.05}));
}

#[tokio::test]
async fn dm_and_chatlog() {
    let s = start().await;
    let (t, s1, s2) = (s.login("teacher", "teacher").await, s.login("kim", "").await, s.login("lee", "").await);
    let mut tw = s.connect("dm1", &t).await;
    let mut s1w = s.connect("dm1", &s1).await;
    let mut s2w = s.connect("dm1", &s2).await;
    drain(&mut tw, 4).await;
    drain(&mut s1w, 3).await;
    drain(&mut s2w, 2).await;

    // kim → teacher 귓속말: 두 사람만 수신
    send(&mut s1w, json!({"type": "DM", "payload": {"to": "teacher", "text": "몰래 질문"}})).await;
    let dm = recv(&mut tw).await;
    assert_eq!(dm["type"], "DM");
    assert_eq!(dm["payload"], json!({"from": "kim", "to": "teacher", "text": "몰래 질문"}));
    assert_eq!(recv(&mut s1w).await["type"], "DM"); // 발신자 에코
    // 제3자 lee에게는 오지 않는다
    assert!(tokio::time::timeout(Duration::from_millis(300), s2w.next()).await.is_err());
    // 없는 상대 → 오류
    send(&mut s1w, json!({"type": "DM", "payload": {"to": "nobody", "text": "?"}})).await;
    assert_eq!(recv(&mut s1w).await["type"], "ERROR");

    assert_eq!(s.get(&format!("/api/chatlog/dm1?token={t}")).await.status(), 200);
    assert_eq!(s.get(&format!("/api/chatlog/dm1?token={s1}")).await.status(), 403);
    let body = s.get(&format!("/api/chatlog/dm1?token={t}")).await.text().await.unwrap();
    let first: Value = serde_json::from_str(body.trim().split('\n').next().unwrap()).unwrap();
    assert_eq!(first["name"], "kim");
    assert_eq!(first["to"], "teacher");
}

#[tokio::test]
async fn survey() {
    let s = start().await;
    let (t, s1, s2) = (s.login("teacher", "teacher").await, s.login("kim", "").await, s.login("lee", "").await);
    let mut tw = s.connect("sv1", &t).await;
    let mut s1w = s.connect("sv1", &s1).await;
    let mut s2w = s.connect("sv1", &s2).await;
    drain(&mut tw, 4).await;
    drain(&mut s1w, 3).await;
    drain(&mut s2w, 2).await;

    // 학생은 설문 발행 불가
    send(&mut s1w, json!({"type": "SURVEY_START", "payload": {"question": "?", "options": ["A", "B"]}})).await;
    assert_eq!(recv(&mut s1w).await["type"], "ERROR");

    // 익명 설문: 전원 SURVEY_START 수신, 투표 시 전원 집계 수신, 명단은 비공개
    send(&mut tw, json!({"type": "SURVEY_START", "payload": {"question": "점심?", "options": ["한식", "중식"], "anonymous": true}})).await;
    for w in [&mut tw, &mut s1w, &mut s2w] {
        let m = recv(w).await;
        assert_eq!(m["type"], "SURVEY_START");
        assert_eq!(m["payload"]["options"], json!(["한식", "중식"]));
    }
    send(&mut s1w, json!({"type": "SURVEY_ANSWER", "payload": {"choice": 0}})).await;
    for w in [&mut tw, &mut s1w, &mut s2w] {
        assert_eq!(recv(w).await["payload"]["tally"], json!([1, 0]));
    }
    send(&mut tw, json!({"type": "SURVEY_END"})).await;
    for w in [&mut tw, &mut s1w, &mut s2w] {
        assert_eq!(recv(w).await["payload"]["tally"], json!([1, 0]));
    }

    // 실명 설문: 투표 명단은 강사에게만
    send(&mut tw, json!({"type": "SURVEY_START", "payload": {"question": "?", "options": ["O", "X"], "anonymous": false}})).await;
    for w in [&mut tw, &mut s1w, &mut s2w] {
        recv(w).await;
    }
    send(&mut s1w, json!({"type": "SURVEY_ANSWER", "payload": {"choice": 1}})).await;
    assert_eq!(recv(&mut tw).await["type"], "SURVEY_RESULT");
    let voters = recv(&mut tw).await;
    assert_eq!(voters["type"], "SURVEY_VOTERS");
    assert_eq!(voters["payload"]["votes"], json!({"kim": 1}));
    recv(&mut s1w).await;
    recv(&mut s2w).await; // SURVEY_RESULT만 수신
    assert!(tokio::time::timeout(Duration::from_millis(300), s1w.next()).await.is_err());
}

#[tokio::test]
async fn admin_and_chat_history() {
    let s = start().await;
    let admin = s.login("admin", "admin").await;
    {
        let mut aw = s.connect("h1", &admin).await;
        drain(&mut aw, 2).await; // MEMBERS, STATE
        send(&mut aw, json!({"type": "DRAW", "payload": {"x": 0}})).await; // 관리자도 판서 가능
        assert_eq!(recv(&mut aw).await["type"], "DRAW");
        send(&mut aw, json!({"type": "CHAT", "payload": {"text": "이전 대화"}})).await;
        assert_eq!(recv(&mut aw).await["type"], "CHAT");
    }
    let (s1, s2) = (s.login("kim", "").await, s.login("lee", "").await);
    {
        let mut s1w = s.connect("h1", &s1).await;
        recv(&mut s1w).await; // MEMBERS
        let state = recv(&mut s1w).await;
        assert_eq!(state["type"], "STATE");
        assert_eq!(state["payload"]["chat"], json!([{"name": "admin", "text": "이전 대화"}]));
        send(&mut s1w, json!({"type": "DM", "payload": {"to": "ghost", "text": "x"}})).await;
        assert_eq!(recv(&mut s1w).await["type"], "ERROR"); // 상대 없음
    }
    {
        // kim이 자기 자신에게 보낸 DM은 당사자 기록에만 남는다
        let mut s1w = s.connect("h1", &s1).await;
        drain(&mut s1w, 2).await;
        send(&mut s1w, json!({"type": "DM", "payload": {"to": "kim", "text": "나에게DM"}})).await;
        assert_eq!(recv(&mut s1w).await["type"], "DM");
    }
    let mut s2w = s.connect("h1", &s2).await;
    recv(&mut s2w).await;
    let state = recv(&mut s2w).await;
    assert!(!state["payload"]["chat"].to_string().contains("나에게DM"));
}

#[tokio::test]
async fn chat_history_restored_after_restart() {
    // 서버가 재시작돼도 chatlogs 파일에서 복원된다(새 서버가 같은 폴더를 쓰는 상황)
    let s = start().await;
    let st = s.login("kim", "").await;
    {
        let mut w = s.connect("rs1", &st).await;
        drain(&mut w, 2).await;
        send(&mut w, json!({"type": "CHAT", "payload": {"text": "남아야 함"}})).await;
        recv(&mut w).await;
    }
    let mut cfg = Config::from_env();
    cfg.chatlog_dir = s._dirs.1.path().into();
    cfg.recordings_dir = s._dirs.0.path().into();
    cfg.secret = b"test-secret".to_vec();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap().to_string();
    tokio::spawn(async move { axum::serve(listener, build_app(cfg)).await.unwrap() });
    let (mut w, _) = connect_async(format!("ws://{addr}/ws/rs1?token={st}")).await.unwrap();
    recv(&mut w).await;
    let state = recv(&mut w).await;
    assert_eq!(state["payload"]["chat"][0]["text"], "남아야 함");
}

#[tokio::test]
async fn recording() {
    let s = start().await;
    let (t, st) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let files = {
        let mut tw = s.connect("rec1", &t).await;
        let mut sw = s.connect("rec1", &st).await;
        drain(&mut tw, 3).await;
        drain(&mut sw, 2).await;
        send(&mut sw, json!({"type": "REC_START"})).await;
        assert_eq!(recv(&mut sw).await["type"], "ERROR");
        send(&mut tw, json!({"type": "REC_START"})).await;
        assert_eq!(recv(&mut tw).await["payload"]["recording"], true);
        recv(&mut sw).await;
        send(&mut tw, json!({"type": "SNIPPET", "payload": {"text": "ls"}})).await;
        recv(&mut tw).await;
        recv(&mut sw).await;
        send(&mut tw, json!({"type": "REC_STOP"})).await;
        assert_eq!(recv(&mut tw).await["payload"]["recording"], false);
        let r: Value = s.get(&format!("/api/recordings?token={t}")).await.json().await.unwrap();
        r
    };
    assert_eq!(files.as_array().unwrap().len(), 1);
    assert_eq!(s.get(&format!("/api/recordings?token={st}")).await.status(), 403);
    let file = files[0]["file"].as_str().unwrap();
    let body = s.get(&format!("/api/recordings/rec1/{file}?token={st}")).await.text().await.unwrap();
    let types: Vec<String> = body
        .trim()
        .split('\n')
        .map(|l| serde_json::from_str::<Value>(l).unwrap()["type"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(types, ["REC_START", "SNIPPET", "REC_STOP"]);
    // 경로 이탈 차단
    assert_eq!(s.get(&format!("/api/recordings/..%2Fx/a.jsonl?token={st}")).await.status(), 404);
    assert_eq!(s.get(&format!("/api/recordings/rec1/..%2F..%2Fx.jsonl?token={st}")).await.status(), 404);
}

#[tokio::test]
async fn teacher_leaving_closes_recording() {
    let s = start().await;
    let t = s.login("teacher", "teacher").await;
    {
        let mut tw = s.connect("rec2", &t).await;
        drain(&mut tw, 2).await;
        send(&mut tw, json!({"type": "REC_START"})).await;
        recv(&mut tw).await;
    }
    tokio::time::sleep(Duration::from_millis(300)).await;
    let files: Value = s.get(&format!("/api/recordings?token={t}")).await.json().await.unwrap();
    let file = files[0]["file"].as_str().unwrap();
    let body = s.get(&format!("/api/recordings/rec2/{file}?token={t}")).await.text().await.unwrap();
    assert!(body.trim().ends_with(r#""type":"REC_STOP"}"#), "마지막 줄이 REC_STOP이어야 한다: {body}");
}

#[tokio::test]
async fn bad_token_rejected_and_token_tamper_detected() {
    let s = start().await;
    assert!(connect_async(format!("ws://{}/ws/r1?token=bad", s.addr)).await.is_err());
    let cfg = Config { secret: b"test-secret".to_vec(), ..Config::from_env() };
    assert!(lecture_server::auth::verify_token(&cfg, "x.y").is_none());
    let token = lecture_server::auth::make_token(&cfg, "kim", "student");
    let claims = lecture_server::auth::verify_token(&cfg, &token).unwrap();
    assert_eq!((claims.name.as_str(), claims.role.as_str()), ("kim", "student"));
    // 변조 방지
    let (body, sig) = token.split_once('.').unwrap();
    assert!(lecture_server::auth::verify_token(&cfg, &format!("{body}.{}x", sig)).is_none());
}

#[tokio::test]
async fn serves_pages() {
    let s = start().await;
    for path in ["/", "/replay", "/static/index.html"] {
        let r = s.get(path).await;
        assert_eq!(r.status(), 200, "{path}");
        assert!(r.text().await.unwrap().contains("<html"));
    }
}

#[tokio::test]
async fn chat_file_upload() {
    let s = start().await;
    let (t1, t2) = (s.login("kim", "").await, s.login("lee", "").await);
    let mut w1 = s.connect("u1", &t1).await;
    drain(&mut w1, 2).await;
    let mut w2 = s.connect("u1", &t2).await;
    drain(&mut w1, 1).await; // 새 입장자 MEMBERS
    drain(&mut w2, 2).await;
    let up = |tok: &str, name: &str, data: Vec<u8>, room: &str| {
        let req = s.http.post(s.url(&format!("/api/upload/{room}?token={tok}&name={}", enc(name)))).body(data);
        async move { req.send().await.unwrap() }
    };
    let r = up(&t1, "../수업 자료.pdf", b"%PDF-1.4 hello".to_vec(), "u1").await;
    assert_eq!(r.status(), 200);
    let f: Value = r.json().await.unwrap();
    assert_eq!((f["name"].as_str().unwrap(), f["size"].as_u64().unwrap()), ("수업 자료.pdf", 14));
    for w in [&mut w1, &mut w2] {
        let m = recv(w).await;
        assert_eq!(m["type"], "CHAT");
        assert_eq!(m["payload"]["file"], f);
        assert_eq!(m["payload"]["name"], "kim");
    }
    let url = format!("/api/files/u1/{}/{}", f["id"].as_str().unwrap(), enc(f["name"].as_str().unwrap()));
    assert_eq!(s.get(&url).await.status(), 401);
    let d = s.http.get(s.url(&format!("{url}?token={t2}"))).send().await.unwrap();
    assert!(d.headers()["content-disposition"].to_str().unwrap().starts_with("attachment"));
    assert_eq!(d.headers()["x-content-type-options"], "nosniff");
    assert_eq!(d.bytes().await.unwrap().as_ref(), b"%PDF-1.4 hello");
    let d = s.http.get(s.url(&format!("{url}?token={t2}&inline=1"))).send().await.unwrap();
    assert!(d.headers()["content-disposition"].to_str().unwrap().starts_with("attachment"));
    // 거절 규칙
    assert_eq!(up(&t1, "a.exe", b"x".to_vec(), "u1").await.status(), 400);
    assert_eq!(up(&t1, "a.txt", vec![], "u1").await.status(), 400);
    assert_eq!(up(&t1, "a.txt", b"x".to_vec(), "other").await.status(), 403);
    assert_eq!(up("bad", "a.txt", b"x".to_vec(), "u1").await.status(), 401);
    assert_eq!(up(&t1, "big.bin", vec![0u8; 20 * 1024 * 1024 + 1], "u1").await.status(), 413);
    let bad = s.http.get(s.url(&format!("/api/files/u1/{}/..%2Fx?token={t1}", f["id"].as_str().unwrap()))).send().await.unwrap();
    assert_eq!(bad.status(), 404);
    assert_eq!(s.http.get(s.url(&format!("/api/files/u1/zzzzzzzzzzzz/a.txt?token={t1}"))).send().await.unwrap().status(), 404);
    // 이미지는 inline 허용
    let img: Value = up(&t1, "p.png", b"\x89PNG".to_vec(), "u1").await.json().await.unwrap();
    let r = s.http.get(s.url(&format!("/api/files/u1/{}/p.png?token={t1}&inline=1", img["id"].as_str().unwrap()))).send().await.unwrap();
    assert_eq!(r.headers()["content-type"], "image/png");
    assert_eq!(r.headers()["content-disposition"], "inline");
    // 다시 입장하면 기록에 파일 정보가 남는다
    let mut w3 = s.connect("u1", &t2).await;
    recv(&mut w3).await; // MEMBERS
    let st = recv(&mut w3).await;
    let names: Vec<&str> = st["payload"]["chat"].as_array().unwrap().iter().filter_map(|c| c["file"]["name"].as_str()).collect();
    assert_eq!(names, vec!["수업 자료.pdf", "p.png"]);
}

#[tokio::test]
async fn login_kinds() {
    let s = start().await;
    let post = |b: Value| s.post("/api/login", b);
    let r = post(json!({"name": "teacher", "password": "teacher", "kind": "student"})).await;
    assert_eq!(r.status(), 401);
    assert!(r.json::<Value>().await.unwrap()["detail"].as_str().unwrap().contains("강의자 탭"));
    let r: Value = post(json!({"name": "kim", "kind": "student"})).await.json().await.unwrap();
    assert_eq!(r["role"], "student");
    let r: Value = post(json!({"name": "teacher", "password": "teacher", "kind": "staff"})).await.json().await.unwrap();
    assert_eq!(r["role"], "teacher");
    assert_eq!(post(json!({"name": "teacher", "password": "x", "kind": "staff"})).await.status(), 401);
    assert_eq!(post(json!({"name": "kim", "kind": "staff"})).await.status(), 401);
    let r: Value = post(json!({"name": "admin", "password": "admin", "kind": "staff"})).await.json().await.unwrap();
    assert_eq!(r["role"], "admin");
}

#[tokio::test]
async fn student_screen_share() {
    let s = start().await;
    let (t, s1, s2) = (s.login("teacher", "teacher").await, s.login("kim", "").await, s.login("lee", "").await);
    let mt = |tok: &str, path: &str, action: &str| {
        let body = json!({"action": action, "path": path, "password": tok});
        async { s.post("/api/mediamtx/auth", body).await.status().as_u16() }
    };
    let mut tw = s.connect("sh1", &t).await;
    drain(&mut tw, 2).await;
    let mut w1 = s.connect("sh1", &s1).await;
    drain(&mut tw, 1).await;
    drain(&mut w1, 2).await;
    let mut w2 = s.connect("sh1", &s2).await;
    drain(&mut tw, 1).await;
    drain(&mut w1, 1).await;
    drain(&mut w2, 2).await;
    assert_eq!(mt(&s1, "sh1__share", "publish").await, 403); // 허용 전
    send(&mut w1, json!({"type": "SHARE_REQUEST", "payload": {}})).await;
    let st = recv(&mut tw).await;
    assert_eq!(st["type"], "SHARE_STATE");
    assert_eq!(st["payload"], json!({"presenter": null, "requests": ["kim"], "requested": false}));
    let own = recv(&mut w1).await; // 수강생은 자기 요청 여부만 안다
    assert_eq!((&own["payload"]["requests"], &own["payload"]["requested"]), (&json!([]), &json!(true)));
    recv(&mut w2).await;
    send(&mut w2, json!({"type": "SHARE_GRANT", "payload": {"name": "kim"}})).await; // 수강생은 허용 불가
    assert_eq!(recv(&mut w2).await["type"], "ERROR");
    send(&mut tw, json!({"type": "SHARE_GRANT", "payload": {"name": "lee"}})).await; // 요청 안 한 사람
    send(&mut tw, json!({"type": "SHARE_GRANT", "payload": {"name": "kim"}})).await;
    assert_eq!(recv(&mut tw).await["payload"], json!({"presenter": "kim", "requests": [], "requested": false}));
    recv(&mut w1).await;
    recv(&mut w2).await;
    assert_eq!(mt(&s1, "sh1__share", "publish").await, 200);
    assert_eq!(mt(&s2, "sh1__share", "publish").await, 403);
    assert_eq!(mt(&t, "sh1__share", "publish").await, 403);
    assert_eq!(mt(&t, "sh1", "publish").await, 200);
    assert_eq!(mt(&s1, "sh1", "publish").await, 403);
    assert_eq!(mt(&s2, "sh1__share", "read").await, 200);
    send(&mut w1, json!({"type": "SHARE_END", "payload": {}})).await;
    assert!(recv(&mut tw).await["payload"]["presenter"].is_null());
    recv(&mut w1).await;
    recv(&mut w2).await;
    assert_eq!(mt(&s1, "sh1__share", "publish").await, 403);
    send(&mut w2, json!({"type": "SHARE_REQUEST", "payload": {}})).await;
    for w in [&mut tw, &mut w1, &mut w2] {
        recv(w).await;
    }
    send(&mut tw, json!({"type": "SHARE_GRANT", "payload": {"name": "lee"}})).await;
    for w in [&mut tw, &mut w1, &mut w2] {
        recv(w).await;
    }
    send(&mut tw, json!({"type": "SHARE_STOP", "payload": {}})).await;
    for w in [&mut tw, &mut w1, &mut w2] {
        assert!(recv(w).await["payload"]["presenter"].is_null());
    }
}

#[tokio::test]
async fn board_background() {
    let s = start().await;
    let (t, k) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let mut tw = s.connect("bg1", &t).await;
    drain(&mut tw, 2).await;
    let mut sw = s.connect("bg1", &k).await;
    drain(&mut tw, 1).await;
    recv(&mut sw).await;
    assert_eq!(recv(&mut sw).await["payload"]["boardBg"], "video");
    send(&mut tw, json!({"type": "BOARD_BG", "payload": {"bg": "green"}})).await;
    assert_eq!(recv(&mut sw).await["payload"], json!({"bg": "green"}));
    recv(&mut tw).await;
    send(&mut tw, json!({"type": "BOARD_BG", "payload": {"bg": "<script>"}})).await; // 무시
    send(&mut sw, json!({"type": "BOARD_BG", "payload": {"bg": "black"}})).await; // 수강생은 불가
    assert_eq!(recv(&mut sw).await["type"], "ERROR");
    let mut late = s.connect("bg1", &k).await;
    recv(&mut late).await;
    assert_eq!(recv(&mut late).await["payload"]["boardBg"], "green");
}

#[tokio::test]
async fn shapes_and_icons() {
    let s = start().await;
    let (t, k) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let mut tw = s.connect("sp1", &t).await;
    drain(&mut tw, 2).await;
    let mut sw = s.connect("sp1", &k).await;
    drain(&mut tw, 1).await;
    drain(&mut sw, 2).await;
    send(&mut sw, json!({"type": "SHAPE", "payload": {"kind": "rect", "x1": 0, "y1": 0, "x2": 1, "y2": 1}})).await;
    assert_eq!(recv(&mut sw).await["type"], "ERROR");
    send(&mut tw, json!({"type": "SHAPE", "payload": {"kind": "star-fish", "x1": 0}})).await; // 무시
    send(&mut tw, json!({"type": "ICON", "payload": {"icon": "<img>", "x": 0.5}})).await; // 무시
    send(&mut tw, json!({"type": "SHAPE", "payload": {"kind": "arrow", "x1": -3, "y1": 0.2, "x2": 9, "y2": 0.8, "color": "red", "fill": "yes"}})).await;
    let m = recv(&mut sw).await;
    assert_eq!(m["type"], "SHAPE");
    assert_eq!(m["payload"], json!({"kind": "arrow", "x1": 0.0, "y1": 0.2, "x2": 1.0, "y2": 0.8, "color": "#ff3b30", "fill": false, "w": 0.005}));
    recv(&mut tw).await;
    send(&mut tw, json!({"type": "ICON", "payload": {"icon": "star", "x": 0.3, "y": 0.4, "size": 5, "color": "#00ff00"}})).await;
    assert_eq!(recv(&mut sw).await["payload"], json!({"icon": "star", "x": 0.3, "y": 0.4, "size": 0.4, "color": "#00ff00"}));
}

#[tokio::test]
async fn draw_modes_and_width() {
    let s = start().await;
    let t = s.login("teacher", "teacher").await;
    let mut tw = s.connect("dw1", &t).await;
    drain(&mut tw, 2).await;
    send(&mut tw, json!({"type": "DRAW", "payload": {"x": 2, "y": 0.5, "color": "#ffcc00", "isDragging": true, "mode": "highlight", "w": 0.035}})).await;
    assert_eq!(recv(&mut tw).await["payload"], json!({"x": 1.0, "y": 0.5, "color": "#ffcc00", "isDragging": true, "mode": "highlight", "w": 0.035}));
    send(&mut tw, json!({"type": "DRAW", "payload": {"x": 0.1, "y": 0.1, "color": "red", "mode": "<b>", "w": 99}})).await;
    assert_eq!(recv(&mut tw).await["payload"], json!({"x": 0.1, "y": 0.1, "color": "#ff3b30", "isDragging": false, "mode": "pen", "w": 0.2}));
    send(&mut tw, json!({"type": "DRAW", "payload": {"x": 0.3, "y": 0.3, "mode": "erase", "w": 0}})).await;
    assert_eq!(recv(&mut tw).await["payload"]["w"], 0.001);
}

#[tokio::test]
async fn late_joiner_gets_board() {
    let s = start().await;
    let (t, k) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let mut tw = s.connect("lb1", &t).await;
    drain(&mut tw, 2).await;
    send(&mut tw, json!({"type": "DRAW", "payload": {"x": 0.1, "y": 0.2, "color": "#ff0000", "isDragging": false}})).await;
    send(&mut tw, json!({"type": "TEXT", "payload": {"x": 0.3, "y": 0.3, "text": "hi", "color": "#000000", "size": 20}})).await;
    drain(&mut tw, 2).await;
    let mut late = s.connect("lb1", &k).await;
    recv(&mut late).await;
    let st = recv(&mut late).await;
    let board = st["payload"]["board"].as_array().unwrap().clone();
    assert_eq!(board.len(), 2);
    assert_eq!(board[0]["type"], "DRAW");
    assert_eq!(board[1]["type"], "TEXT");
    send(&mut tw, json!({"type": "CLEAR", "payload": {}})).await;
    drain(&mut tw, 2).await;
    let mut late2 = s.connect("lb1", &k).await;
    recv(&mut late2).await;
    assert_eq!(recv(&mut late2).await["payload"]["board"].as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn poll_results_saved() {
    let s = start().await;
    let (t, k) = (s.login("teacher", "teacher").await, s.login("kim", "").await);
    let mut tw = s.connect("pr1", &t).await;
    drain(&mut tw, 2).await;
    let mut kw = s.connect("pr1", &k).await;
    drain(&mut tw, 1).await;
    drain(&mut kw, 2).await;
    assert_eq!(s.get(&format!("/api/polls/pr1?token={t}")).await.status(), 404); // 아직 없음
    // 실명 설문 + 익명 설문 + 퀴즈
    send(&mut tw, json!({"type": "SURVEY_START", "payload": {"question": "점심?", "options": ["한식", "중식"], "anonymous": false}})).await;
    drain(&mut tw, 1).await;
    drain(&mut kw, 1).await;
    send(&mut kw, json!({"type": "SURVEY_ANSWER", "payload": {"choice": 1}})).await;
    drain(&mut tw, 2).await; // SURVEY_RESULT + SURVEY_VOTERS
    send(&mut tw, json!({"type": "SURVEY_END"})).await;
    drain(&mut tw, 1).await;
    send(&mut tw, json!({"type": "QUIZ_START", "payload": {"question": "1+1=2?", "options": ["O", "X"]}})).await;
    drain(&mut tw, 1).await;
    send(&mut tw, json!({"type": "QUIZ_END"})).await;
    drain(&mut tw, 1).await;
    assert_eq!(s.get(&format!("/api/polls/pr1?token={k}")).await.status(), 403); // 수강생 불가
    let body = s.get(&format!("/api/polls/pr1?token={t}")).await.text().await.unwrap();
    let rows: Vec<Value> = body.lines().map(|l| serde_json::from_str(l).unwrap()).collect();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0]["kind"], "survey");
    assert_eq!(rows[0]["tally"], json!([0, 1]));
    assert_eq!(rows[0]["votes"], json!({"kim": 1}));
    assert_eq!(rows[1]["kind"], "quiz");
    assert_eq!(rows[1]["question"], "1+1=2?");
}
