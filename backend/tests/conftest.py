import os
import tempfile
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://datasentry:datasentry@localhost:5432/datasentry_test")
os.environ["ENVIRONMENT"] = "test"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="ds-test-storage-")
os.environ["SCHEDULER_MODE"] = "off"
os.environ["RATE_LIMIT_UPLOAD_PER_MIN"] = "1000"
os.environ["RATE_LIMIT_AUTH_PER_MIN"] = "1000"
os.environ["RATE_LIMIT_PREDICTIONS_PER_MIN"] = "1000"
os.environ["CRON_SECRET"] = "test-cron-secret"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789-abcdefghijkl"


@pytest.fixture(scope="session")
def migrated():
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from alembic import command

    url = os.environ["DATABASE_URL"]
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    return True


@pytest.fixture()
def client(migrated):
    from fastapi.testclient import TestClient

    from app.core.ratelimit import limiter
    from app.main import app

    limiter.reset()
    with TestClient(app) as c:
        yield c


def register(client, role_note="t"):
    email = f"{role_note}-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "correct horse battery", "display_name": "Tester",
                                                   "workspace_name": "Test"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()


@pytest.fixture()
def auth(client):
    headers, _ = register(client)
    return headers
