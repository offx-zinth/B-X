from datetime import datetime, timedelta
from jose import jwt
import hashlib, os, hmac
from .config import settings

def hash_pw(p: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${h}"
def verify_pw(p: str, h: str) -> bool:
    try: salt, want = h.split("$")
    except ValueError: return False
    got = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 100_000).hex()
    return hmac.compare_digest(got, want)
def make_token(tenant_id: str, user_id: str, email: str) -> str:
    payload = {"tenant_id": tenant_id, "sub": user_id, "email": email, "exp": datetime.utcnow() + timedelta(hours=12)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
def decode_token(t: str) -> dict: return jwt.decode(t, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
