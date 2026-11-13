"""Counts for the console's dashboard and sidebar."""

from fastapi import APIRouter

from app.applications.models import Application
from app.clients.models import OAuthClient
from app.dashboard.schemas import StatsOut
from app.identity.models import Session
from app.users.models import User
from utilities.common import utcnow

router = APIRouter(prefix="/v1/admin/stats", tags=["Admin: Dashboard"])


@router.get("", response_model=StatsOut, summary="Users, applications, live sessions and service clients")
async def stats():
    live = Session.filter(revoked_at__isnull=True, expires_at__gt=utcnow())
    return {
        "users": await User.all().count(),
        "disabled_users": await User.filter(is_active=False).count(),
        "applications": await Application.all().count(),
        "application_keys": await Application.all().order_by("key").values_list("key", flat=True),
        "active_sessions": await live.count(),
        "session_users": len(set(await live.values_list("user_id", flat=True))),
        "service_clients": await OAuthClient.filter(type="confidential", is_active=True).count(),
    }
