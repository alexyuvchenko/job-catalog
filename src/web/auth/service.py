"""Local accounts: password checks, session tokens, and where sign-in may send you."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

SESSION_COOKIE = "session"
SESSION_DAYS = 30
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


class AccountError(Exception):
    """A rejected username or password. ``code`` is a translation key."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class User:
    id: int
    username: str


def check_username(value: str) -> str:
    name = value.strip()
    if not name or len(name) > 64 or any(ord(ch) < 32 or ch == "\x7f" for ch in name):
        raise AccountError("username_invalid")
    return name


def check_password(value: str) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 200:
        raise AccountError("password_invalid")
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=32 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True when ``password`` matches ``stored``. A tampered hash is a mismatch."""
    try:
        kind, n, r, p, salt_hex, hash_hex = stored.split("$")
        expected = bytes.fromhex(hash_hex)
        # Only hashes this app wrote are accepted, so a changed row cannot ask for a huge scrypt.
        if (
            kind != "scrypt"
            or int(n) != _SCRYPT_N
            or int(r) != _SCRYPT_R
            or int(p) != _SCRYPT_P
            or len(expected) != 32
        ):
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=32,
            maxmem=32 * 1024 * 1024,
        )
    except TypeError, ValueError:
        return False
    return hmac.compare_digest(digest, expected)


# Compared when the username is missing, so that attempt takes about as long as a real one.
DUMMY_HASH = hash_password("not-a-real-password")


def fresh_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry() -> str:
    return (datetime.now() + timedelta(days=SESSION_DAYS)).replace(microsecond=0).isoformat(sep=" ")


def expires_soon(expires_at: str) -> bool:
    """True in the last week of a session, which is when an active browser gets more time."""
    soon = (datetime.now() + timedelta(days=7)).replace(microsecond=0).isoformat(sep=" ")
    return expires_at <= soon


def safe_next(value: str) -> str:
    """A path on this site to open after sign-in. Anything else becomes the catalog."""
    raw = value.strip()
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return "/"
    path, _, query = raw.partition("?")
    if path != "/" or any(ch in query for ch in "\r\n"):
        return "/"
    return "/" if not query else "/?" + query
