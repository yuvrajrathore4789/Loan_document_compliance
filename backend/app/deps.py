"""Auth dependencies and demo-user seeding."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import database
from app.config import get_settings
from app.models import User
from app.utils.security import decode_token, hash_password

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@dataclass
class CurrentUser:
    username: str
    role: str


def get_current_user(token: str = Depends(oauth2), db: Session = Depends(database.get_db)) -> CurrentUser:
    payload = decode_token(token)
    err = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.", headers={"WWW-Authenticate": "Bearer"})
    if not payload:
        raise err
    user = db.scalar(select(User).where(User.username == payload.get("sub"), User.is_active.is_(True)))
    if user is None:
        raise err
    return CurrentUser(user.username, user.role)  # role comes from the DB, not the token


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required.")
    return user


def seed_demo_users(db: Session) -> int:
    """Create demo users only when the users table is empty (credentials come from env, see README)."""
    s = get_settings()
    if not s.seed_demo_users or db.scalar(select(func.count(User.id))):
        return 0
    db.add_all([User(username="admin", password_hash=hash_password(s.demo_admin_password), role="admin", full_name="Demo Admin"),
                User(username="reviewer", password_hash=hash_password(s.demo_reviewer_password), role="reviewer", full_name="Demo Reviewer"),
                User(username="reviewer2", password_hash=hash_password(s.demo_reviewer_password), role="reviewer", full_name="Demo Reviewer Two")])
    db.commit()
    return 3
