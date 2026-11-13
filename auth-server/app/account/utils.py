from app.account.schemas import SessionOut
from app.identity.models import Session


def session_view(session: Session, current_sid: str | None = None) -> SessionOut:
    return SessionOut(
        id=session.public_id,
        ip=session.ip,
        user_agent=session.user_agent,
        amr=session.amr,
        auth_time=session.auth_time,
        expires_at=session.expires_at,
        current=str(session.public_id) == current_sid,
    )
