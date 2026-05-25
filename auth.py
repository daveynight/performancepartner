import os
import bcrypt
from typing import Optional
from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
SESSION_COOKIE = "pp_session"
SESSION_MAX_AGE = 86400 * 7  # 7 days

_signer = URLSafeTimedSerializer(SECRET_KEY)


class NotAuthenticatedException(Exception):
    pass


class NotAuthorizedException(Exception):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_session_token(user_id: int) -> str:
    return _signer.dumps(user_id, salt="session")


def _decode_token(token: str) -> Optional[int]:
    try:
        return _signer.loads(token, salt="session", max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = _decode_token(token)
    if not user_id:
        return None
    from database import get_db, fetchone
    with get_db() as conn:
        return fetchone(conn, "SELECT * FROM users WHERE id=? AND is_active=1", (user_id,))


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise NotAuthenticatedException()
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user["role"] not in ("admin", "manager"):
        raise NotAuthorizedException()
    return user
