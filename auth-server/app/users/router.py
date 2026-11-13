"""User administration. No auth code here: access is declared in app/security/policy.py."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from tortoise.expressions import Q, Subquery
from tortoise.transactions import in_transaction

from app.account.schemas import FactorOut, SessionOut
from app.account.utils import session_view
from app.applications.models import UserRole
from app.audit.services import Actor, record_audit
from app.identity.services import live_sessions, revoke_user_sessions
from app.security.deps import current_actor
from app.users import services
from app.users.models import User
from app.users.schemas import (
    PasswordReset,
    UserCreate,
    UserDetail,
    UserListItem,
    UserOut,
    UserRolesSet,
    UserUpdate,
)
from utilities.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/v1/admin/users", tags=["Admin: Users"])


@router.get("", response_model=Page[UserListItem],
            summary="Users by username, with search, status and application filters")
async def list_users(
    page: PageParams = Depends(),
    q: str | None = Query(None, max_length=128, description="Matches username, email or name"),
    active: bool | None = None,
    app: str | None = Query(None, max_length=32, description="Only users holding a role in this application"),
):
    qs = User.all().order_by("username")
    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
    if active is not None:
        qs = qs.filter(is_active=active)
    if app:
        qs = qs.filter(id__in=Subquery(UserRole.filter(role__app__key=app.upper()).values("user_id")))
    result = await paginate(qs, page)
    result["items"] = await services.list_items(result["items"])
    return result


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, actor: Actor = Depends(current_actor)):
    return await services.create_user(data, actor)


@router.get("/{public_id}", response_model=UserDetail, summary="A user with their access in every application")
async def get_user(public_id: UUID):
    return await services.user_detail(await services.get_user(public_id))


@router.patch("/{public_id}", response_model=UserOut, summary="Edit profile, or disable / enable")
async def update_user(public_id: UUID, data: UserUpdate, actor: Actor = Depends(current_actor)):
    return await services.update_user(public_id, data, actor)


@router.put("/{public_id}/roles", status_code=status.HTTP_204_NO_CONTENT,
            summary="Replace the user's roles in one application")
async def set_user_roles(public_id: UUID, data: UserRolesSet, actor: Actor = Depends(current_actor)):
    await services.set_user_roles(public_id, data.app_key, data.role_ids, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{public_id}/sessions", response_model=list[SessionOut], summary="The user's live sessions")
async def user_sessions(public_id: UUID):
    user = await services.get_user(public_id)
    return [session_view(session) for session in await live_sessions(user.id)]


@router.delete("/{public_id}/sessions", status_code=status.HTTP_204_NO_CONTENT,
               summary="End every session of the user")
async def end_user_sessions(public_id: UUID, actor: Actor = Depends(current_actor)):
    user = await services.get_user(public_id)
    async with in_transaction():
        count = await revoke_user_sessions(user.id)
        await record_audit(actor, "session.revoke_all", target=str(public_id), details={"count": count})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{public_id}/password", status_code=status.HTTP_204_NO_CONTENT,
             summary="Set a new password and end every session")
async def reset_password(public_id: UUID, data: PasswordReset, actor: Actor = Depends(current_actor)):
    await services.reset_password(await services.get_user(public_id), data.new_password, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{public_id}/mfa", response_model=list[FactorOut], summary="The user's confirmed MFA factors")
async def user_factors(public_id: UUID):
    factors = await services.user_factors(await services.get_user(public_id))
    return [FactorOut(id=f.public_id, type=f.type, name=f.name, confirmed_at=f.confirmed_at) for f in factors]


@router.delete("/{public_id}/mfa", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove every MFA factor (lost device) and end every session")
async def reset_mfa(public_id: UUID, actor: Actor = Depends(current_actor)):
    await services.reset_mfa(await services.get_user(public_id), actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
