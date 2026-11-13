"""Who is calling. The access decision itself belongs to app/security/policy.py; these only read what the
policy guard stored on the request."""

from fastapi import Depends, Request

from app.audit.services import Actor
from app.tokens.schemas import Claims
from utilities.common import client_ip
from utilities.exceptions import AppError


def current_claims(request: Request) -> Claims:
    """The caller's verified claims, as stored by the policy guard."""
    claims = getattr(request.state, "claims", None)
    if claims is None:
        raise AppError(401, "not_authenticated", "Authentication required")
    return claims


def current_actor(request: Request, claims: Claims = Depends(current_claims)) -> Actor:
    return Actor(id=claims.sub, ip=client_ip(request))
