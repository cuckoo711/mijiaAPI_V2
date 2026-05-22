"""Security helpers for administrator sessions and API keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

HASH_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 260_000


@dataclass(frozen=True)
class SecretHash:
    """Structured representation of a stored secret hash."""

    algorithm: str
    iterations: int
    salt: str
    digest: str

    def serialize(self) -> str:
        """Serialize the hash in a compact, versioned form."""

        return f"pbkdf2_{self.algorithm}${self.iterations}${self.salt}${self.digest}"

    @classmethod
    def parse(cls, value: str) -> "SecretHash":
        """Parse a hash created by :func:`hash_secret`."""

        algorithm, iterations, salt, digest = value.split("$", 3)
        if not algorithm.startswith("pbkdf2_"):
            raise ValueError("Unsupported hash algorithm")
        return cls(
            algorithm=algorithm.removeprefix("pbkdf2_"),
            iterations=int(iterations),
            salt=salt,
            digest=digest,
        )


def hash_secret(secret: str, salt: Optional[str] = None) -> str:
    """Hash a password, session token, or API key."""

    resolved_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM,
        secret.encode("utf-8"),
        resolved_salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return SecretHash(
        algorithm=HASH_ALGORITHM,
        iterations=PBKDF2_ITERATIONS,
        salt=resolved_salt,
        digest=digest,
    ).serialize()


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Verify a secret against a stored PBKDF2 hash."""

    parsed = SecretHash.parse(stored_hash)
    candidate = hashlib.pbkdf2_hmac(
        parsed.algorithm,
        secret.encode("utf-8"),
        parsed.salt.encode("utf-8"),
        parsed.iterations,
    ).hex()
    return hmac.compare_digest(candidate, parsed.digest)


def generate_session_token() -> str:
    """Generate an administrator session token."""

    return f"ms_{secrets.token_urlsafe(32)}"


def generate_api_key() -> str:
    """Generate an API key shown once to the administrator."""

    return f"mk_live_{secrets.token_urlsafe(32)}"


def secret_prefix(secret: str) -> str:
    """Return a stable, non-sensitive prefix for lookup and display."""

    return secret[:18]
