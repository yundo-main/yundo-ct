//! HMAC-SHA256 서명 토큰. 파이썬 서버와 같은 형식이라 서로의 토큰을 검증할 수 있다.
//! 형식: base64url(JSON{name,role,exp}) + "." + base64url(HMAC(body))

use crate::config::Config;
use base64::{Engine, engine::general_purpose::URL_SAFE};
use hmac::{Hmac, KeyInit, Mac};
use serde_json::Value;
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};

const TOKEN_TTL: u64 = 60 * 60 * 12;

#[derive(Clone, Debug)]
pub struct Claims {
    pub name: String,
    pub role: String,
}

impl Claims {
    /// 강사 권한(강사 또는 관리자)
    pub fn is_staff(&self) -> bool {
        is_staff(&self.role)
    }
}

pub fn is_staff(role: &str) -> bool {
    role == "teacher" || role == "admin"
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn mac(cfg: &Config) -> Hmac<Sha256> {
    Hmac::<Sha256>::new_from_slice(&cfg.secret).expect("HMAC은 모든 키 길이를 허용한다")
}

pub fn make_token(cfg: &Config, name: &str, role: &str) -> String {
    let claims = serde_json::json!({ "name": name, "role": role, "exp": now() + TOKEN_TTL });
    let body = URL_SAFE.encode(claims.to_string());
    let mut m = mac(cfg);
    m.update(body.as_bytes());
    format!("{body}.{}", URL_SAFE.encode(m.finalize().into_bytes()))
}

pub fn verify_token(cfg: &Config, token: &str) -> Option<Claims> {
    let (body, sig) = token.split_once('.')?;
    let sig = URL_SAFE.decode(sig).ok()?;
    let mut m = mac(cfg);
    m.update(body.as_bytes());
    m.verify_slice(&sig).ok()?; // 상수 시간 비교
    let claims: Value = serde_json::from_slice(&URL_SAFE.decode(body).ok()?).ok()?;
    if claims.get("exp")?.as_f64()? <= now() as f64 {
        return None;
    }
    Some(Claims {
        name: claims.get("name")?.as_str()?.to_string(),
        role: claims.get("role")?.as_str()?.to_string(),
    })
}

/// 상수 시간 문자열 비교(비밀번호용)
fn eq_ct(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    let mut diff = (a.len() ^ b.len()) as u8;
    for i in 0..a.len().max(b.len()) {
        diff |= a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(0);
    }
    diff == 0
}

/// 강사/관리자는 비밀번호 필요, 그 외 이름은 수강생으로 입장.
/// `kind`: "staff"(강의자 탭: 계정만) / "student"(수강생 탭: 강의자 아이디 사용 불가) / 그 외(이전 방식).
pub fn login(cfg: &Config, name: &str, password: &str, kind: &str) -> Option<String> {
    let is_account = cfg.users.iter().any(|(n, _, _)| n == name);
    if (kind == "staff" && !is_account) || (kind == "student" && is_account) {
        return None;
    }
    if let Some((_, expected, role)) = cfg.users.iter().find(|(n, _, _)| n == name) {
        return eq_ct(password, expected).then(|| make_token(cfg, name, role));
    }
    (!name.trim().is_empty()).then(|| make_token(cfg, name, "student"))
}
