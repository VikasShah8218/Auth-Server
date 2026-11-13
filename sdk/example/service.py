"""A minimal downstream service.

    AUTH_ISSUER=https://auth.example.com AUTH_APP_KEY=ANPR \
    AUTH_CLIENT_ID=anpr-api AUTH_CLIENT_SECRET=... \
    uvicorn service:app --port 9000
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from auth_sdk import AuthSDK, Principal

auth = AuthSDK(
    issuer=os.environ["AUTH_ISSUER"],
    app_key=os.environ["AUTH_APP_KEY"],
    client_id=os.environ["AUTH_CLIENT_ID"],
    client_secret=os.environ["AUTH_CLIENT_SECRET"],
    state_path=os.environ.get("AUTH_STATE_PATH"),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await auth.start()
    yield
    await auth.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return auth.health()


@app.get("/whoami")
async def whoami(user: Principal = Depends(auth.current_user)) -> dict:
    return {"sub": user.sub, "roles": user.roles}


@app.get("/vehicles")
async def vehicles(_: Principal = Depends(auth.require_perm("vehicle.read"))) -> list[str]:
    return ["JK01AB1234"]
