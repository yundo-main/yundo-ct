//! 환경변수 기반 설정. 파이썬 서버와 같은 변수 이름을 쓴다.

use std::path::PathBuf;

#[derive(Clone)]
pub struct Config {
    pub secret: Vec<u8>,
    /// (이름, 비밀번호, 역할) — 데모 계정. 운영 시 DB로 교체한다.
    pub users: Vec<(String, String, String)>,
    pub recordings_dir: PathBuf,
    pub chatlog_dir: PathBuf,
    pub upload_dir: PathBuf,
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

impl Config {
    pub fn from_env() -> Self {
        let mut users = vec![
            ("teacher".to_string(), env_or("TEACHER_PASSWORD", "teacher"), "teacher".to_string()),
            ("admin".to_string(), env_or("ADMIN_PASSWORD", "admin"), "admin".to_string()),
        ];
        // 강의자 계정 추가: TEACHER_ACCOUNTS="아이디:비밀번호,아이디2:비밀번호2"
        for pair in env_or("TEACHER_ACCOUNTS", "").split(',').filter(|s| !s.is_empty()) {
            if let Some((id, pw)) = pair.split_once(':') {
                if !id.trim().is_empty() && !pw.is_empty() {
                    users.retain(|(n, _, _)| n != id.trim());
                    users.push((id.trim().to_string(), pw.to_string(), "teacher".to_string()));
                }
            }
        }
        Config {
            secret: env_or("LECTURE_SECRET", "dev-secret-change-me").into_bytes(),
            users,
            recordings_dir: env_or("RECORDINGS_DIR", "server/recordings").into(),
            chatlog_dir: env_or("CHATLOG_DIR", "server/chatlogs").into(),
            upload_dir: env_or("UPLOAD_DIR", "server/uploads").into(),
        }
    }
}
