"""Password hashing and opaque session tokens."""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()  # argon2id, library defaults (t=3, m=64 MiB, p=4)
_DUMMY = _ph.hash("not-a-real-password")


def hash_password(password):
    return _ph.hash(password)


def verify_password(stored_hash, password):
    """Constant-ish time: a missing user is checked against a dummy hash by the caller."""
    try:
        return _ph.verify(stored_hash or _DUMMY, password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).digest()


def same(a, b):
    return hmac.compare_digest(str(a).encode(), str(b).encode())
