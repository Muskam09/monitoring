"""SMTP mailer used by Task 3 (activation) and Task 7 (password reset).

In the lab setup we always send through MailHog (docker-compose service
`mailhog`, SMTP on port 1025). You can view every sent email at
http://localhost:8025.

For production you can override SMTP_HOST / SMTP_PORT / SMTP_USER /
SMTP_PASSWORD / SMTP_STARTTLS in the environment to point at a real
provider (Mailtrap, SendGrid, Gmail SMTP, …).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("mailer")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


SMTP_HOST = _env("SMTP_HOST", "mailhog")
SMTP_PORT = int(_env("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER")  # None → no auth (MailHog default)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_STARTTLS = _bool("SMTP_STARTTLS", False)
MAIL_FROM = _env("MAIL_FROM", "DevOps Dashboard <no-reply@dashboard.local>")

APP_BASE_URL = _env("APP_BASE_URL", "http://localhost:5173")


def send_mail(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Never raises — mail failures are logged.

    Rationale: if MailHog is temporarily down we don't want the user's
    registration to fail outright. The link can always be re-sent.
    """
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
            if SMTP_STARTTLS:
                smtp.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
        log.info("Sent mail to %s subject=%r via %s:%s", to, subject, SMTP_HOST, SMTP_PORT)
    except Exception as exc:  # noqa: BLE001
        log.warning("Mail delivery failed to %s via %s:%s — %s",
                    to, SMTP_HOST, SMTP_PORT, exc)


# ─── Templates ─────────────────────────────────────────────────────────
def send_activation_email(to: str, username: str, token: str) -> None:
    link = f"{APP_BASE_URL}/activate/{token}"
    body = (
        f"Привіт, {username}!\n\n"
        "Дякуємо за реєстрацію у DevOps Dashboard.\n"
        "Для активації акаунта перейдіть за посиланням:\n\n"
        f"{link}\n\n"
        "Посилання одноразове і дійсне протягом 24 годин.\n"
    )
    send_mail(to, "Активація акаунта — DevOps Dashboard", body)


def send_password_reset_email(to: str, username: str, token: str) -> None:
    link = f"{APP_BASE_URL}/reset-password/{token}"
    body = (
        f"Привіт, {username}!\n\n"
        "Ми отримали запит на скидання пароля для вашого акаунта.\n"
        "Якщо це були ви, перейдіть за посиланням нижче, щоб обрати новий пароль:\n\n"
        f"{link}\n\n"
        "Посилання одноразове і дійсне протягом 1 години.\n"
        "Якщо запит зробили не ви — просто проігноруйте цей лист.\n"
    )
    send_mail(to, "Скидання пароля — DevOps Dashboard", body)
