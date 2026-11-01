"""Password hashing (PBKDF2-HMAC-SHA256) and signed access tokens (JWT HS256).

Demo-grade authentication for a portfolio project; not a production identity system.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import timedelta

import jwt

from app.config import get_settings
from app.database import utcnow

ITERATIONS = 200_000
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
        return hmac.compare_digest(calc, digest)
    except (ValueError, AttributeError):
        return False


def create_token(username: str, role: str) -> str:
    s = get_settings()
    exp = utcnow() + timedelta(minutes=s.token_ttl_minutes)
    return jwt.encode({"sub": username, "role": role, "exp": int(time.time() + s.token_ttl_minutes * 60)}, s.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


class LoginThrottle:
    """Tiny in-memory brute-force guard: max 5 failures per username per 5 minutes."""

    def __init__(self, limit: int = 5, window_s: int = 300):
        self.limit, self.window, self.fails = limit, window_s, {}

    def blocked(self, username: str) -> bool:
        now = time.time()
        self.fails[username] = [t for t in self.fails.get(username, []) if now - t < self.window]
        return len(self.fails[username]) >= self.limit

    def record_failure(self, username: str) -> None:
        self.fails.setdefault(username, []).append(time.time())

    def reset(self, username: str) -> None:
        self.fails.pop(username, None)


throttle = LoginThrottle()
