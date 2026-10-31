"""Authentication helpers: password hashing + JWT issuance & verification."""
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

import models
from database import get_db

# ─── Configuration (from environment, never hardcoded) ─────────────────
_SECRET_FROM_ENV = os.getenv("JWT_SECRET_KEY")
if _SECRET_FROM_ENV:
    SECRET_KEY: str = _SECRET_FROM_ENV
else:
    # Fail-safe for local dev if someone forgot the .env file.
    # In production this MUST be set explicitly.
    SECRET_KEY = secrets.token_urlsafe(64)
    print(
        "[auth] WARNING: JWT_SECRET_KEY not set in environment — "
        "generated an ephemeral one. Set it in .env for stable tokens."
    )

ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# ─── Password hashing (bcrypt via passlib) ─────────────────────────────
# bcrypt automatically generates a per-password salt and includes it in the
# hash output, so storing just the hash string is enough — verification
# re-derives the salt from the stored hash.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ─── JWT issuance ──────────────────────────────────────────────────────
def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ─── JWT verification / "current user" dependency ──────────────────────
# tokenUrl is the login endpoint — used by Swagger UI's "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login", auto_error=True)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> "models.User":
    """Decode the Bearer JWT and resolve it to a DB user."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if not username:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exc
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is not activated")
    if user.is_locked:
        raise HTTPException(status_code=403, detail="Account is locked by administrator")
    return user


def get_current_admin(
    user: "models.User" = Depends(get_current_user),
) -> "models.User":
    """Dependency: like get_current_user but requires `is_admin=True`."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
