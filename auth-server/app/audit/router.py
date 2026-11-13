"""Reading the audit trail. Access is declared in app/security/policy.py, never here."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.audit.models import AuditLog
from app.audit.schemas import AuditOut
from app.users.models import User
from utilities.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/v1/admin/audit", tags=["Admin: Audit"])


@router.get("", response_model=Page[AuditOut], summary="Audit records, newest first, with filters")
async def list_audit(
    page: PageParams = Depends(),
    actor: str | None = Query(None, max_length=128),
    action: str | None = Query(None, max_length=64),
    app: str | None = Query(None, max_length=32),
    since: datetime | None = None,
    until: datetime | None = None,
):
    qs = AuditLog.all().order_by("-id")
    if actor:
        qs = qs.filter(actor=actor)
    if action:
        qs = qs.filter(action=action)
    if app:
        qs = qs.filter(app=app.upper())
    if since:
        qs = qs.filter(created_at__gte=since)
    if until:
        qs = qs.filter(created_at__lte=until)
    result = await paginate(qs, page)
    result["items"] = await audit_views(result["items"])
    return result


async def audit_views(rows: list[AuditLog]) -> list[AuditOut]:
    """Audit rows with each user actor's username, in one query for the whole page."""
    ids = set()
    for row in rows:
        try:
            ids.add(UUID(row.actor))
        except ValueError:
            pass
    names = dict(await User.filter(public_id__in=list(ids)).values_list("public_id", "username")) if ids else {}
    names = {str(key): value for key, value in names.items()}
    return [
        AuditOut(
            id=row.id,
            actor=row.actor,
            actor_name=names.get(row.actor, row.actor),
            action=row.action,
            target=row.target,
            app=row.app,
            details=row.details,
            ip=row.ip,
            created_at=row.created_at,
        )
        for row in rows
    ]
