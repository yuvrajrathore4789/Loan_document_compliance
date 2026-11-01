from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import database
from app.deps import CurrentUser, get_current_user
from app.models import User
from app.schemas.api import TokenOut, UserOut
from app.services import audit_service as audit
from app.utils.security import create_token, throttle, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    if throttle.blocked(form.username):
        raise HTTPException(429, "Too many failed attempts. Try again later.")
    user = db.scalar(select(User).where(User.username == form.username, User.is_active.is_(True)))
    if not user or not verify_password(form.password, user.password_hash):
        throttle.record_failure(form.username)
        audit.log_event(db, form.username[:64], "LOGIN_FAILED", "user", form.username[:64])
        db.commit()
        raise HTTPException(401, "Incorrect username or password.")
    throttle.reset(form.username)
    audit.log_event(db, user.username, "LOGIN", "user", user.username)
    db.commit()
    return TokenOut(access_token=create_token(user.username, user.role), role=user.role, username=user.username)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return db.scalar(select(User).where(User.username == user.username))


@router.get("/reviewers", response_model=list[str])
def reviewers(_: CurrentUser = Depends(get_current_user), db: Session = Depends(database.get_db)):
    return list(db.scalars(select(User.username).where(User.is_active.is_(True)).order_by(User.username)))
