from fastapi import Depends

from app.security.deps import current_claims
from app.tokens.schemas import Claims
from app.users.models import User
from utilities.exceptions import AppError


async def current_user(claims: Claims = Depends(current_claims)) -> User:
    """The signed-in user. A disabled user is refused even with an unexpired token."""
    user = await User.get_or_none(public_id=claims.sub, is_active=True)
    if user is None:
        raise AppError(401, "invalid_token", "Token has been revoked")
    return user
