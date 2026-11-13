"""Applications, their permissions and roles. No auth code here: access is declared in app/security/policy.py."""

from fastapi import APIRouter, Depends, Response, status

from app.applications import services
from app.applications.models import Application, Permission, Role
from app.applications.schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    MemberOut,
    PermissionCreate,
    PermissionOut,
    PermissionUpdate,
    RoleCreate,
    RoleDetail,
    RoleOut,
    RolePermissionsSet,
    RoleUpdate,
)
from app.audit.services import Actor
from app.security.deps import current_actor
from utilities.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/v1/admin/applications", tags=["Admin: Applications"])


# Applications


@router.get("", response_model=Page[ApplicationOut], summary="All applications, by key")
async def list_applications(page: PageParams = Depends()):
    return await paginate(Application.all().order_by("key"), page)


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED,
             summary="Create an application with its * permission and Admin role")
async def create_application(data: ApplicationCreate, actor: Actor = Depends(current_actor)):
    return await services.create_application(data, actor)


@router.get("/{key}", response_model=ApplicationOut)
async def get_application(key: str):
    return await services.get_app(key)


@router.patch("/{key}", response_model=ApplicationOut, summary="Rename, describe, activate or deactivate")
async def update_application(key: str, data: ApplicationUpdate, actor: Actor = Depends(current_actor)):
    return await services.update_application(key, data, actor)


@router.get("/{key}/members", response_model=list[MemberOut], summary="Users holding any role in the app")
async def list_members(key: str):
    return await services.application_members(await services.get_app(key))


# Permissions


@router.get("/{key}/permissions", response_model=list[PermissionOut], summary="Permissions by bit")
async def list_permissions(key: str, include_retired: bool = False):
    app = await services.get_app(key)
    qs = Permission.filter(app_id=app.id).order_by("bit")
    return await (qs if include_retired else qs.filter(retired_at__isnull=True))


@router.post("/{key}/permissions", response_model=PermissionOut, status_code=status.HTTP_201_CREATED,
             summary="Create a permission on the next free bit (or revive a retired one)")
async def create_permission(key: str, data: PermissionCreate, actor: Actor = Depends(current_actor)):
    return await services.create_permission(key, data, actor)


@router.patch("/{key}/permissions/{permission_id}", response_model=PermissionOut)
async def update_permission(
    key: str, permission_id: int, data: PermissionUpdate, actor: Actor = Depends(current_actor)
):
    return await services.update_permission(key, permission_id, data, actor)


@router.delete("/{key}/permissions/{permission_id}", response_model=PermissionOut,
               summary="Retire a permission. Its bit stays reserved forever")
async def retire_permission(key: str, permission_id: int, actor: Actor = Depends(current_actor)):
    return await services.retire_permission(key, permission_id, actor)


# Roles


@router.get("/{key}/roles", response_model=list[RoleOut])
async def list_roles(key: str):
    app = await services.get_app(key)
    return await Role.filter(app_id=app.id).order_by("name")


@router.post("/{key}/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(key: str, data: RoleCreate, actor: Actor = Depends(current_actor)):
    return await services.create_role(key, data, actor)


@router.get("/{key}/roles/{role_id}", response_model=RoleDetail, summary="A role with its permissions")
async def get_role(key: str, role_id: int):
    app = await services.get_app(key)
    role = await services.get_role(app, role_id)
    return RoleDetail(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=await services.role_permissions(role),
    )


@router.patch("/{key}/roles/{role_id}", response_model=RoleOut)
async def update_role(key: str, role_id: int, data: RoleUpdate, actor: Actor = Depends(current_actor)):
    return await services.update_role(key, role_id, data, actor)


@router.delete("/{key}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(key: str, role_id: int, actor: Actor = Depends(current_actor)):
    await services.delete_role(key, role_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{key}/roles/{role_id}/permissions", response_model=list[PermissionOut],
            summary="Replace a role's permissions")
async def set_role_permissions(
    key: str, role_id: int, data: RolePermissionsSet, actor: Actor = Depends(current_actor)
):
    return await services.set_role_permissions(key, role_id, data.permission_ids, actor)
