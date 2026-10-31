"""Task 2 — Google reCAPTCHA v2 server-side verification.

Design:
- If RECAPTCHA_SECRET_KEY is NOT configured in the environment, the
  verifier returns True (bypass). This lets the lab run offline and lets
  the switch flip to "real" by just setting the keys.
- The frontend hides the widget when VITE_RECAPTCHA_SITE_KEY is empty, so
  the two sides stay in sync automatically.
"""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("captcha")

RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "").strip()
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def is_enabled() -> bool:
    return bool(RECAPTCHA_SECRET_KEY)


async def verify(token: str | None, remote_ip: str | None = None) -> bool:
    """Return True if captcha passes (or if captcha is disabled)."""
    if not is_enabled():
        log.debug("reCAPTCHA disabled (no RECAPTCHA_SECRET_KEY) — bypassing")
        return True
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            data = {"secret": RECAPTCHA_SECRET_KEY, "response": token}
            if remote_ip:
                data["remoteip"] = remote_ip
            r = await client.post(RECAPTCHA_VERIFY_URL, data=data)
        if r.status_code != 200:
            log.warning("reCAPTCHA siteverify HTTP %s", r.status_code)
            return False
        body = r.json()
        ok = bool(body.get("success"))
        if not ok:
            log.info("reCAPTCHA rejected: %s", body)
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("reCAPTCHA verify failed: %s", exc)
        return False
