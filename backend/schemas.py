from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Telemetry (agent → backend) ───────────────────────────────────────
class ContainerMetricCreate(BaseModel):
    container_id: str
    name: str
    state: str
    cpu_percent: float
    ram_percent: float


class HostMetricCreate(BaseModel):
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    containers: List[ContainerMetricCreate] = []


# ─── User registration / login ─────────────────────────────────────────
# Lab requirements for passwords:
#   • at least 8 characters
#   • upper- AND lower-case letters
#   • at least one digit
#   • at least one special character (anything that is neither letter nor digit)
# (Optional stretch: block common/weak passwords — basic blacklist below.)

_COMMON_WEAK_PASSWORDS = {
    "password", "password1", "password123", "qwerty", "qwerty123",
    "12345678", "123456789", "1234567890", "letmein", "welcome",
    "admin", "admin123", "root", "iloveyou", "monkey", "dragon",
    "abc12345", "Passw0rd", "Password1", "Password123", "Qwerty123",
}


def _validate_password_policy(v: str) -> str:
    """Shared password-policy validator (reused by register + password reset)."""
    if len(v) < 8:
        raise ValueError("Пароль має містити мінімум 8 символів")
    if not re.search(r"[a-z]", v):
        raise ValueError("Пароль має містити хоча б одну малу літеру")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Пароль має містити хоча б одну велику літеру")
    if not re.search(r"\d", v):
        raise ValueError("Пароль має містити хоча б одну цифру")
    if not re.search(r"[^A-Za-z0-9]", v):
        raise ValueError(
            "Пароль має містити хоча б один спеціальний символ "
            "(не літера й не цифра)"
        )
    if v.lower() in {p.lower() for p in _COMMON_WEAK_PASSWORDS}:
        raise ValueError("Цей пароль занадто поширений — оберіть складніший")
    return v


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr
    password: str
    # Task 2 — reCAPTCHA token from the frontend widget.
    # Optional in the schema so the field is accepted when captcha is off;
    # when the server has RECAPTCHA_SECRET_KEY, main.py enforces it.
    captcha_token: Optional[str] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", v):
            raise ValueError(
                "Ім'я користувача може містити лише літери, цифри та символи _.-"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_policy(v)


class Token(BaseModel):
    access_token: str
    token_type: str


class LoginResponse(BaseModel):
    """Response envelope for /api/login.

    `access_token` is populated on full success.
    `twofa_required=True` + `twofa_ticket` means "credentials OK, now POST
    the OTP to /api/2fa/verify-login". We never issue a JWT until the OTP
    checks out.
    """
    access_token: Optional[str] = None
    token_type: str = "bearer"
    twofa_required: bool = False
    twofa_ticket: Optional[str] = None


class TwoFALoginVerify(BaseModel):
    ticket: str
    code: str


class UserProfile(BaseModel):
    """Returned by /api/me — the authenticated user's own profile."""
    id: int
    username: str
    email: EmailStr
    role: str
    is_active: bool
    is_2fa_enabled: bool
    is_admin: bool
    is_locked: bool

    class Config:
        from_attributes = True


# ─── Task 2 — public captcha config ────────────────────────────────────
class CaptchaConfig(BaseModel):
    enabled: bool
    site_key: Optional[str] = None


# ─── Task 3 — activation ───────────────────────────────────────────────
class ResendActivationRequest(BaseModel):
    email: EmailStr


# ─── Task 4 — admin login log view ─────────────────────────────────────
class LoginLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    username_attempted: Optional[str] = None
    ip_address: str
    status: str
    reason: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class AdminUserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str
    is_active: bool
    is_locked: bool
    is_admin: bool
    is_2fa_enabled: bool
    failed_login_attempts: int
    locked_until: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Task 5 — 2FA ──────────────────────────────────────────────────────
class TwoFAEnrollResponse(BaseModel):
    secret: str
    otpauth_url: str
    qr_png_data_url: str


class TwoFAVerifyRequest(BaseModel):
    code: str


class TwoFADisableRequest(BaseModel):
    password: str  # confirm identity before switching 2FA off


# ─── Task 7 — password recovery ────────────────────────────────────────
class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_policy(v)


# ─── Hosts (dashboard) ─────────────────────────────────────────────────
class HostOut(BaseModel):
    id: int
    name: str
    ip_address: Optional[str] = None
    is_online: bool

    class Config:
        from_attributes = True


class HostMetricOut(BaseModel):
    id: int
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    timestamp: datetime

    class Config:
        from_attributes = True
