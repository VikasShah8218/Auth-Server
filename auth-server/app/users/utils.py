"""Password hashing and rules. Argon2id through argon2-cffi."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from utilities.exceptions import AppError

MIN_PASSWORD_LENGTH = 4

_hasher = PasswordHasher()
_dummy_hash = _hasher.hash("no-such-account")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def spend_password_time(password: str) -> None:
    """Do the work of a real check, so an unknown username can't be told apart by how long the response
    takes."""
    verify_password(password, _dummy_hash)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password(password: str, username: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(422, "weak_password", f"Password must have at least {MIN_PASSWORD_LENGTH} characters")
    # if username.lower() in password.lower():
    #     raise AppError(422, "weak_password", "Password must not contain the username")
