"""Auth crypto: Argon2id primary, PBKDF2 fallback, JWT access+refresh.

Hash format is versioned so work factors stay agile:
  $argon2id$v=19$...  (argon2-cffi PHC string)
  $pbkdf2$210000$salt$hex  (legacy fallback, verified but rehashed on login)
"""
from datetime import datetime, timedelta, timezone
from jose import jwt
import hashlib
import hmac
import os
from .config import settings

_PBKDF2_ITERATIONS = 210_000

try:
    from argon2 import PasswordHasher as _ArgonHasher
    from argon2.exceptions import VerifyMismatchError as _ArgonMismatch
    _ARGON = _ArgonHasher(time_cost=3, memory_cost=65536, parallelism=4)
except Exception:  # minimal envs without argon2-cffi: PBKDF2 only
    _ARGON = None
    _ArgonMismatch = Exception


def _pbkdf2_hash(p: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return f"$pbkdf2${_PBKDF2_ITERATIONS}${salt}${h}"


def hash_pw(p: str) -> str:
    if _ARGON is not None:
        try:
            return _ARGON.hash(p)
        except Exception:
            pass
    # legacy custom format "salt$hex" (100k) is still verified in verify_pw
    return _pbkdf2_hash(p)


def verify_pw(p: str, h: str) -> bool:
    if not p or not h:
        return False
    if h.startswith("$argon2"):
        if _ARGON is None:
            return False
        try:
            return _ARGON.verify(h, p)
        except _ArgonMismatch:
            return False
        except Exception:
            return False
    if h.startswith("$pbkdf2$"):
        try:
            _, _, iters, salt, want = h.split("$", 4)
            got = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), int(iters)).hex()
            return hmac.compare_digest(got, want)
        except Exception:
            return False
    # legacy "salt$hex" @100k from the prototype
    try:
        salt, want = h.split("$")
        got = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 100_000).hex()
        return hmac.compare_digest(got, want)
    except Exception:
        return False


def needs_rehash(h: str) -> bool:
    """True when a verified hash should be upgraded to Argon2id."""
    return not h.startswith("$argon2")


def _sign_key() -> str:
    if settings.JWT_ALG.upper() in ("RS256", "ES256", "EdDSA") and settings.JWT_PRIVATE_KEY:
        return settings.JWT_PRIVATE_KEY.replace("\\n", "\n")
    return settings.JWT_SECRET


def _verify_key() -> str:
    if settings.JWT_ALG.upper() in ("RS256", "ES256", "EdDSA"):
        if settings.JWT_PUBLIC_KEY:
            return settings.JWT_PUBLIC_KEY.replace("\\n", "\n")
        if settings.JWT_PRIVATE_KEY:  # HSM-less dev: derive verify from private
            return settings.JWT_PRIVATE_KEY.replace("\\n", "\n")
    return settings.JWT_SECRET


def _encode(payload: dict) -> str:
    return jwt.encode(payload, _sign_key(), algorithm=settings.JWT_ALG)


def make_token(tenant_id: str, user_id: str, email: str) -> str:
    """Back-compat 12h token (prototype behaviour). Prefer make_access_token."""
    payload = {"tenant_id": tenant_id, "sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return _encode(payload)


def make_access_token(tenant_id: str, user_id: str, email: str, role: str = "Viewer") -> str:
    payload = {"tenant_id": tenant_id, "sub": user_id, "email": email, "role": role,
               "typ": "access",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_MINUTES)}
    return _encode(payload)


def make_refresh_token(tenant_id: str, user_id: str) -> str:
    payload = {"tenant_id": tenant_id, "sub": user_id, "typ": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_DAYS)}
    return _encode(payload)


def decode_token(t: str) -> dict:
    return jwt.decode(t, _verify_key(), algorithms=[settings.JWT_ALG])
