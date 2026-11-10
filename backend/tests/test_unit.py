"""Unit tests — isolated logic, no DB, no network, no external services.

Covers:
  • Password policy in schemas.UserCreate (positive + negative cases)
  • JWT creation & decoding in auth.create_access_token / jose.jwt
  • TOTP generation & verification in totp.*
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from jose import jwt
from pydantic import ValidationError

import auth
import totp
from schemas import UserCreate


# ────────────────────────────────────────────────────────────────────────
# 1. Password policy — POSITIVE cases
#    Policy (schemas._validate_password_policy):
#      ≥ 8 chars · lower · upper · digit · one non-alphanumeric special
#      and not in the common-weak blacklist.
# ────────────────────────────────────────────────────────────────────────
class TestPasswordPolicy:
    def test_strong_password_is_accepted(self):
        """UT-01 (positive): a password that satisfies every rule passes."""
        user = UserCreate(
            username="alice",
            email="alice@example.com",
            password="Str0ng!Passw0rd",  # 15 chars, upper+lower+digit+special
        )
        assert user.password == "Str0ng!Passw0rd"

    def test_minimum_length_boundary_is_accepted(self):
        """UT-02 (positive): exactly 8 chars + all classes is still valid."""
        # Length == 8 is the boundary; make sure we don't off-by-one it.
        user = UserCreate(
            username="bob",
            email="bob@example.com",
            password="Aa1!aaaa",  # exactly 8 chars
        )
        assert len(user.password) == 8

    # ── NEGATIVE cases ────────────────────────────────────────────────
    def test_password_too_short_is_rejected(self):
        """UT-03 (negative): < 8 chars → ValidationError."""
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                username="carol",
                email="carol@example.com",
                password="Aa1!aa",  # 6 chars
            )
        # The Ukrainian error message from _validate_password_policy must
        # surface in the Pydantic error list.
        assert "8 символів" in str(exc.value)

    def test_password_missing_digit_is_rejected(self):
        """UT-04 (negative): no digit → ValidationError."""
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                username="dave",
                email="dave@example.com",
                password="NoDigitHere!",  # has upper+lower+special, zero digits
            )
        assert "цифру" in str(exc.value)

    def test_password_missing_uppercase_is_rejected(self):
        """UT-05 (negative): no uppercase letter → ValidationError."""
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                username="erin",
                email="erin@example.com",
                password="all-lower-1!",  # no A-Z
            )
        assert "велику літеру" in str(exc.value)


# ────────────────────────────────────────────────────────────────────────
# 2. JWT creation & decoding (auth.create_access_token)
# ────────────────────────────────────────────────────────────────────────
class TestJWT:
    def test_create_and_decode_access_token_roundtrip(self):
        """UT-06: a freshly-issued JWT decodes back to its original claims."""
        token = auth.create_access_token({"sub": "alice", "role": "viewer"})
        assert isinstance(token, str) and token.count(".") == 2  # header.payload.sig

        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])

        assert payload["sub"] == "alice"
        assert payload["role"] == "viewer"
        # create_access_token must always inject an `exp` claim.
        assert "exp" in payload
        # Expiry must sit in the future and inside the configured window.
        exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        assert exp_dt > now
        assert exp_dt <= now + timedelta(
            minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES + 1
        )

    def test_expired_token_is_rejected(self):
        """UT-07: a token whose `exp` is already in the past must not decode."""
        # Issue a token that expired 1 second ago by requesting a negative TTL.
        token = auth.create_access_token({"sub": "bob"}, expires_minutes=-1)
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])


# ────────────────────────────────────────────────────────────────────────
# 3. TOTP generation & verification (totp.new_secret / totp.verify)
# ────────────────────────────────────────────────────────────────────────
class TestTOTP:
    def test_new_secret_is_valid_base32_and_unique(self):
        """UT-08: new_secret() produces a decodable base32 string
        of expected length, and two calls never collide."""
        s1 = totp.new_secret()
        s2 = totp.new_secret()

        assert s1 != s2
        # pyotp default is 32 base32 chars (160 bits of entropy).
        assert len(s1) == 32
        # Must round-trip through pyotp itself — the real consumer.
        assert pyotp.TOTP(s1).now().isdigit()

    def test_verify_accepts_current_code_and_rejects_wrong_one(self):
        """UT-09: totp.verify() is True for the live code and False
        for an obviously wrong one, and gracefully rejects garbage input."""
        secret = totp.new_secret()
        good_code = pyotp.TOTP(secret).now()

        assert totp.verify(secret, good_code) is True
        # A deterministically-wrong 6-digit code — flip one digit.
        wrong_code = "0" * 6 if good_code != "000000" else "111111"
        assert totp.verify(secret, wrong_code) is False
        # Guard-clause behaviour: non-digit / empty inputs must not crash.
        assert totp.verify(secret, "") is False
        assert totp.verify(secret, "abcdef") is False
        assert totp.verify("", good_code) is False
