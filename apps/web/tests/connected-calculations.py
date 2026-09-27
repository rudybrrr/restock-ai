"""Disposable PostgreSQL + real worker + HTTP API + browser acceptance.

Run from services/api with its venv. Only specialist reasoning is controlled;
numerical calculation, persistence, session auth and manager reads are real.
The browser forwards API requests to the isolated server, never fixture JSON.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.config import Settings
from src.main import create_app
from tests.conftest import database_url
from tests.test_assessment_worker import queue_manager_assessment, invoke_worker, models
from src import assessment_worker as worker


def main():
    os.environ.setdefault("TEST_DATABASE_URL", Settings().database_url)
    isolated = database_url.__wrapped__()
    url = next(isolated)
    server = None
    thread = None
    try:
        settings = Settings(
            database_url=url,
            manager_password=SecretStr("test-manager-password"),
            agent_token=SecretStr("test-agent-token"),
            allowed_origins=["https://frontend.example", "http://localhost:3025"],
            cookie_secure=False,
            enable_development_calculator=True,
        )
        with pytest.MonkeyPatch.context() as patch:
            with TestClient(create_app(settings), base_url="https://api.example") as client:
                run = queue_manager_assessment(client)
                result = client.get(f"/api/v1/manager/runs/{run['id']}/calculation-results").json()
                assert result["status"] == "NOT_RECORDED"
                assert result["run_status"] == "QUEUED"
            patch.setattr(worker, "build_organiser_reasoning_models", lambda settings: models())
            app = create_app(settings)

            # Test-only trigger on an isolated loopback server, never a production route.
            @app.post("/_test/finish")
            def finish():
                completed = invoke_worker(url)
                assert completed.run_id == run["id"]
                assert completed.publication_status == "PUBLISHED"
                return {"finished": True}

            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8031, log_level="warning"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 15
            while not server.started:
                if time.monotonic() > deadline or not thread.is_alive():
                    raise RuntimeError("Isolated API failed to start")
                time.sleep(0.05)
            web = Path(__file__).resolve().parents[1]
            env = {**os.environ, "CONNECTED_RUN_ID": run["id"], "CONNECTED_API_URL": "http://127.0.0.1:8031"}
            subprocess.run(["node", "tests/connected-calculations.cjs"], cwd=web, env=env, check=True)
        print("PASS: queued selection -> real worker completion -> PostgreSQL -> automatic browser refresh; isolated database disposed afterward.")
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Isolated API has not stopped; database cleanup deferred")
        isolated.close()


if __name__ == "__main__":
    main()
