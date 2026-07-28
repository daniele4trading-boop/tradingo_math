"""Password hashing, signed-cookie sessions and login rate limiting.

Stdlib only (hashlib/hmac/secrets) so the VPS needs no crypto packages.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters_s, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


class SessionManager:
    """HMAC-signed session tokens: user.expiry.signature (no server storage)."""

    def __init__(self, secret: str, hours: float = 12.0):
        if not secret:
            raise ValueError("session secret must not be empty")
        self._key = secret.encode("utf-8")
        self.ttl_sec = int(hours * 3600)

    def _sign(self, payload: str) -> str:
        sig = hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).digest()
        return _b64e(sig)

    def create(self, username: str) -> str:
        expiry = int(time.time()) + self.ttl_sec
        payload = f"{_b64e(username.encode('utf-8'))}.{expiry}"
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str | None) -> str | None:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = f"{parts[0]}.{parts[1]}"
        if not hmac.compare_digest(self._sign(payload), parts[2]):
            return None
        try:
            expiry = int(parts[1])
            username = _b64d(parts[0]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        if time.time() > expiry:
            return None
        return username


class RateLimiter:
    """Track login failures per key (IP / username); lockout window on abuse."""

    def __init__(self, max_attempts: int = 5, window_sec: int = 900):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._failures: dict[str, list[float]] = {}

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_sec
        self._failures[key] = [t for t in self._failures.get(key, []) if t > cutoff]

    def is_locked(self, key: str) -> bool:
        now = time.time()
        self._prune(key, now)
        return len(self._failures.get(key, [])) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = time.time()
        self._prune(key, now)
        self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def retry_after_sec(self, key: str) -> int:
        fails = self._failures.get(key) or []
        if not fails:
            return 0
        return max(0, int(fails[0] + self.window_sec - time.time()))
