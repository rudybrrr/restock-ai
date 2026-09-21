import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Iterator[Path]:
    """Use an explicit writable test temp directory with the managed runner."""
    root = Path(os.environ.get("RESTOCK_TEST_TMP", ".pytest-local-tmp"))
    root.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    path = root / f"{safe_name}-{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def writable_python_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid mode-700 temp directories rejected by the managed Windows runner."""

    def managed_mkdtemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | os.PathLike[str] | None = None,
    ) -> str:
        root = Path(dir or tempfile.gettempdir())
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{prefix or 'tmp'}{uuid4().hex}{suffix or ''}"
        path.mkdir()
        return os.fspath(path)

    monkeypatch.setattr(tempfile, "mkdtemp", managed_mkdtemp)


@pytest.fixture
def database_url() -> Iterator[str]:
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        pytest.fail(
            "Set TEST_DATABASE_URL to a PostgreSQL role allowed to create test databases"
        )
    url = make_url(admin_url)
    name = "restock_test_" + uuid4().hex
    connect_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(connect_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    test_url = url.set(drivername="postgresql+psycopg", database=name).render_as_string(
        hide_password=False
    )
    try:
        env = {**os.environ, "DATABASE_URL": test_url}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True
        )
        # Re-running seed must preserve the same API-visible records.
        for _ in range(2):
            subprocess.run([sys.executable, "-m", "src.seed"], env=env, check=True)
        yield test_url
    finally:
        with psycopg.connect(connect_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    from src.config import Settings
    from src.main import create_app

    settings = Settings(
        database_url=database_url,
        manager_password=SecretStr("test-manager-password"),
        agent_token=SecretStr("test-agent-token"),
        allowed_origins=["https://frontend.example"],
        cookie_secure=True,
        cookie_samesite="lax",
        enable_development_calculator=True,
    )
    with TestClient(
        create_app(settings),
        base_url="https://api.example",
        raise_server_exceptions=False,
    ) as test_client:
        yield test_client


@pytest.fixture
def reject_audit_write(
    database_url: str, request: pytest.FixtureRequest
) -> Iterator[None]:
    """Inject a real PostgreSQL write failure; assertions stay at the HTTP seam."""
    url = (
        make_url(database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(url, autocommit=True) as conn:
        action = getattr(request, "param", None)
        predicate = (
            sql.SQL("false")
            if action is None
            else sql.SQL("action <> {}").format(sql.Literal(action))
        )
        conn.execute(
            sql.SQL(
                "ALTER TABLE audit_entries ADD CONSTRAINT test_unavailable CHECK ({}) NOT VALID"
            ).format(predicate)
        )
        try:
            yield
        finally:
            conn.execute("ALTER TABLE audit_entries DROP CONSTRAINT test_unavailable")
