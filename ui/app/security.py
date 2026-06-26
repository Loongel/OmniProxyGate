from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AdminUser, SessionToken

SESSION_COOKIE = os.getenv("SESSION_COOKIE_NAME", "nggm_session")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))

from .passwords import hash_password, verify_password


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(db: Session, user: AdminUser, response: Response) -> str:
    raw = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    session = SessionToken(user_id=user.id, token_hash=token_hash(raw), expires_at=expires)
    db.add(session)
    db.commit()
    secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        httponly=True,
        secure=secure,
        samesite="lax",
        expires=expires,
        max_age=SESSION_DAYS * 86400,
        path="/",
    )
    return raw


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def purge_expired_sessions(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.execute(delete(SessionToken).where(SessionToken.expires_at < now))
    db.commit()


def admin_count(db: Session) -> int:
    return len(db.execute(select(AdminUser.id)).scalars().all())


def current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
    cookie_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> Optional[AdminUser]:
    api_token = os.getenv("OMNI_AGENT_API_TOKEN", "")
    supplied_api_token = request.headers.get("X-OMNI-API-TOKEN", "")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        supplied_api_token = supplied_api_token or auth_header.split(" ", 1)[1].strip()
    if api_token and supplied_api_token and hmac.compare_digest(api_token, supplied_api_token):
        return db.execute(select(AdminUser).order_by(AdminUser.id.asc())).scalar_one_or_none()

    token = cookie_token or request.headers.get("X-NGGM-Session")
    if not token:
        return None
    purge_expired_sessions(db)
    session = db.execute(select(SessionToken).where(SessionToken.token_hash == token_hash(token))).scalar_one_or_none()
    if not session:
        return None
    if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    return db.get(AdminUser, session.user_id)


def require_user(user: Optional[AdminUser] = Depends(current_user_optional)) -> AdminUser:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return user


def remove_current_session(
    db: Session,
    response: Response,
    request: Request,
    cookie_token: Optional[str] = None,
) -> None:
    token = cookie_token or request.headers.get("X-NGGM-Session")
    if token:
        db.execute(delete(SessionToken).where(SessionToken.token_hash == token_hash(token)))
        db.commit()
    clear_session_cookie(response)
