"""Manager credential checks and durable session lifecycle."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import compare_digest, token_urlsafe

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from src.config import Settings
from src.database import manager_sessions
from src.errors import ApiError
from src.schemas import LoginRequest


def same_secret(left: str, right: str) -> bool:
    return compare_digest(left.encode(), right.encode())


def create_manager_session(
    session: Session, settings: Settings, credentials: LoginRequest, old_token: str
) -> str:
    password = settings.manager_password.get_secret_value()
    if not password or not (
        same_secret(credentials.username, settings.manager_username)
        and same_secret(credentials.password, password)
    ):
        raise ApiError(401, "UNAUTHENTICATED", "Invalid manager credentials")
    token = token_urlsafe(32)
    now = datetime.now(UTC)
    session.execute(
        delete(manager_sessions).where(
            (manager_sessions.c.expires_at <= now)
            | (manager_sessions.c.token_hash == sha256(old_token.encode()).hexdigest())
        )
    )
    session.execute(
        insert(manager_sessions).values(
            token_hash=sha256(token.encode()).hexdigest(),
            username=credentials.username,
            expires_at=now + timedelta(hours=settings.session_hours),
        )
    )
    session.commit()
    return token


def revoke_manager_session(session: Session, token: str) -> None:
    session.execute(
        delete(manager_sessions).where(
            manager_sessions.c.token_hash == sha256(token.encode()).hexdigest()
        )
    )
    session.commit()
