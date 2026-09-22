"""Passwords and tokens. Small enough to read in one sitting, which is the
only way anybody ever checks that an auth layer does what it claims.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

SECRET = os.environ.get("MBS_SECRET", "mbs-dev-secret-change-me")
ALGO = "HS256"
TOKEN_DAYS = 14


def hash_password(raw: str) -> str:
    # bcrypt hashes at most 72 bytes and raises on more, so cut there rather
    # than letting a long passphrase 500 the login route.
    return bcrypt.hashpw(raw.encode()[:72], bcrypt.gensalt()).decode()


def check_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first.")
    try:
        payload = jwt.decode(header[7:], SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise HTTPException(401, "That session has expired.")
    user = db.get(User, int(payload.get("sub", 0)))
    if not user or not user.is_active:
        raise HTTPException(401, "That account is no longer active.")
    return user


def manager_only(user: User = Depends(current_user)) -> User:
    if user.role != "manager":
        raise HTTPException(403, "Managers only.")
    return user
