from pydantic import BaseModel


class StatsOut(BaseModel):
    users: int
    disabled_users: int
    applications: int
    application_keys: list[str]
    active_sessions: int
    # People behind the live sessions (one person can be signed in on several devices).
    session_users: int
    service_clients: int
