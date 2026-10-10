"""SDK tests run the real FastAPI app in-process (backend + Postgres test DB) through FastAPI's TestClient,
which is an httpx.Client, so every SDK call exercises the actual endpoints."""
import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://datasentry:datasentry@localhost:5432/datasentry_test")
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("STORAGE_DIR", "/tmp/datasentry-sdk-test-storage")
os.environ["SCHEDULER_MODE"] = "off"
os.environ["SECRET_KEY"] = "sdk-test-secret-key-0123456789-abcdefgh"
os.environ["RATE_LIMIT_UPLOAD_PER_MIN"] = "1000"
os.environ["RATE_LIMIT_AUTH_PER_MIN"] = "1000"


@pytest.fixture(scope="session")
def app_client():
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(app_client):
    from datasentry import DataSentry

    app_client.headers.pop("X-API-Key", None)
    email = f"sdk-{uuid.uuid4().hex[:8]}@example.com"
    r = app_client.post("/api/v1/auth/register", json={"email": email, "password": "sdk password 123", "display_name": "SDK"})
    token = r.json()["access_token"]
    key = app_client.post("/api/v1/api-keys", json={"name": "sdk-test", "role": "editor"},
                          headers={"Authorization": f"Bearer {token}"}).json()["secret"]
    app_client.headers.pop("Authorization", None)
    return DataSentry(api_key=key, http_client=app_client)
