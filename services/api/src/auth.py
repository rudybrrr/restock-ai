from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import Settings
from src.database import get_session, manager_sessions
from src.errors import ApiError
from src.schemas import Identity, LoginRequest
from src.sessions import create_manager_session, revoke_manager_session, same_secret

COOKIE = "restock_session"
SessionDep = Annotated[Session, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)
cookie = APIKeyCookie(name=COOKIE, auto_error=False)
router = APIRouter(prefix="/auth", tags=["Access"])


def require_browser_origin(request: Request) -> None:
    # Also required at login to prevent login CSRF.
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise ApiError(403, "ORIGIN_DENIED", "Supply an explicitly allowed Origin")


def authenticate(
    request: Request,
    session: SessionDep,
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session_token: Annotated[str | None, Depends(cookie)],
) -> Identity:
    settings: Settings = request.app.state.settings
    if authorization is not None:
        expected = settings.agent_token.get_secret_value()
        if expected and same_secret(authorization.credentials, expected):
            return Identity(role="agent", username="agent")
        raise ApiError(401, "UNAUTHENTICATED", "Invalid agent credential")
    if session_token:
        row = (
            session.execute(
                select(manager_sessions).where(
                    manager_sessions.c.token_hash
                    == sha256(session_token.encode()).hexdigest(),
                    manager_sessions.c.expires_at > datetime.now(UTC),
                )
            )
            .mappings()
            .first()
        )
        if row and row["username"] == settings.manager_username:
            return Identity(role="manager", username=row["username"])
    raise ApiError(401, "UNAUTHENTICATED", "Sign in or supply an agent credential")


IdentityDep = Annotated[Identity, Depends(authenticate)]


def require_manager(identity: IdentityDep) -> Identity:
    if identity.role != "manager":
        raise ApiError(
            403, "MANAGER_REQUIRED", "This action requires a manager session"
        )
    return identity


def require_agent(identity: IdentityDep) -> Identity:
    if identity.role != "agent":
        raise ApiError(
            403, "AGENT_REQUIRED", "This action requires an agent credential"
        )
    return identity


@router.post(
    "/login", response_model=Identity, dependencies=[Depends(require_browser_origin)]
)
def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> Identity:
    settings: Settings = request.app.state.settings
    token = create_manager_session(
        session, settings, body, request.cookies.get(COOKIE, "")
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_hours * 3600,
    )
    response.headers["Cache-Control"] = "no-store"
    return Identity(role="manager", username=body.username)


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_manager), Depends(require_browser_origin)],
)
def logout(request: Request, session: SessionDep) -> Response:
    revoke_manager_session(session, request.cookies.get(COOKIE, ""))
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE,
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite=request.app.state.settings.cookie_samesite,
    )
    return response


@router.get("/me", response_model=Identity)
def me(identity: IdentityDep) -> Identity:
    return identity
