"""Password hashing (hashlib.scrypt) and session token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024
SESSION_TTL_HOURS = 8
SESSION_COOKIE = "dce_session"
API_KEY_HEADER = "X-API-Key"
API_KEY_PREFIX = "dce_"
PASSWORD_MIN_LENGTH = 12  # the single password policy: used by seeding, password change, and admin user creation
PASSWORD_MAX_LENGTH = 256  # bounds scrypt work per request; matches the login body limit


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    enc = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${enc(salt)}${enc(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
                                dklen=len(expected), maxmem=_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Used to keep login timing similar when the username does not exist.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def password_policy_error(password: str) -> str | None:
    """Return a user-facing message when the password breaks the policy, otherwise None."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
    return None


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_id_for(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_api_key_token() -> str:
    """A 256-bit random token. Shown once at creation; only its hash is stored."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def api_key_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
