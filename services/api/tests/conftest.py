import os
import subprocess
import sys
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session")
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
    )
    with TestClient(
        create_app(settings), base_url="https://api.example"
    ) as test_client:
        yield test_client
