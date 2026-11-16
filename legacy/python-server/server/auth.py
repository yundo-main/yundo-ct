"""간단한 HMAC 서명 토큰 인증 (외부 라이브러리 없음). 운영 시 SECRET과 USERS를 환경변수/DB로 교체한다."""

import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.environ.get("LECTURE_SECRET", "dev-secret-change-me").encode()
TOKEN_TTL = 60 * 60 * 12

# 데모 계정: 이름 -> (비밀번호, 역할)
USERS = {
    "teacher": (os.environ.get("TEACHER_PASSWORD", "teacher"), "teacher"),
    "admin": (os.environ.get("ADMIN_PASSWORD", "admin"), "admin"),
}
# 강의자 계정을 더 추가하려면 TEACHER_ACCOUNTS="아이디:비밀번호,아이디2:비밀번호2" (비밀번호에 쉼표·콜론 불가)
for _pair in filter(None, os.environ.get("TEACHER_ACCOUNTS", "").split(",")):
    _id, _, _pw = _pair.partition(":")
    if _id.strip() and _pw:
        USERS[_id.strip()] = (_pw, "teacher")


def _sign(data: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.new(SECRET, data, hashlib.sha256).digest()).decode()


def make_token(name: str, role: str) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps({"name": name, "role": role, "exp": int(time.time()) + TOKEN_TTL}).encode()
    ).decode()
    return f"{body}.{_sign(body.encode())}"


def verify_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(body.encode())):
            return None
        claims = json.loads(base64.urlsafe_b64decode(body))
        return claims if claims["exp"] > time.time() else None
    except Exception:
        return None


def login(name: str, password: str, kind: str = "auto") -> str | None:
    """강의자 계정은 비밀번호 필요, 그 외 이름은 수강생으로 입장.
    kind: "staff"(강의자 탭: 계정만 허용) / "student"(수강생 탭: 강의자 아이디는 쓸 수 없음) / "auto"(둘 다, 이전 방식)."""
    if kind == "staff" and name not in USERS:
        return None
    if kind == "student" and name in USERS:
        return None
    if name in USERS:
        expected, role = USERS[name]
        return make_token(name, role) if hmac.compare_digest(password, expected) else None
    return make_token(name, "student") if name.strip() else None
