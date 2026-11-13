"""Encryption at rest and opaque tokens. Never hand-written cryptography: AES-GCM from `cryptography`."""

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from settings.settings import settings

_NONCE_BYTES = 12


def encrypt(plaintext: str, context: str) -> str:
    """AES-GCM under the master key. The context binds a value to its purpose, so a ciphertext copied into
    another row or column won't decrypt there."""
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(settings.master_key_bytes).encrypt(nonce, plaintext.encode(), context.encode())
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt(ciphertext: str, context: str) -> str:
    raw = base64.urlsafe_b64decode(ciphertext.encode())
    return (
        AESGCM(settings.master_key_bytes)
        .decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], context.encode())
        .decode()
    )


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """For long random values only. Passwords use Argon2."""
    return hashlib.sha256(raw.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    """S256: base64url(sha256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
