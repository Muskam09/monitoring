"""Task 5 — TOTP (RFC 6238) 2FA helpers using pyotp."""
from __future__ import annotations

import base64
import io
import os

import pyotp
import qrcode

TOTP_ISSUER = os.getenv("TOTP_ISSUER", "DevOps Dashboard")


def new_secret() -> str:
    """Generate a fresh base32 TOTP secret (160 bits)."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    """otpauth:// URL that Google Authenticator / Authy can import."""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=TOTP_ISSUER
    )


def qr_png_data_url(uri: str) -> str:
    """Return a `data:image/png;base64,…` URL ready for `<img src=…>`."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify(secret: str, code: str) -> bool:
    """Return True if `code` matches current TOTP window for `secret`.

    `valid_window=1` accepts the previous/next 30-second step too, which
    tolerates small clock drift between server and the user's phone.
    """
    if not secret or not code or not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
