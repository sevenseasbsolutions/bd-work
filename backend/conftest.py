"""Test wiring: a throwaway SQLite file, made fresh for every test.

The database URL has to be set before `app.db` is imported, because that module
builds the engine at import time. Nothing here mocks anything — every test
below runs the real routes against a real database.
"""
from __future__ import annotations

import os
import tempfile

_TMP = os.path.join(tempfile.gettempdir(), "mbs-test.db")
os.environ["MBS_DATABASE_URL"] = "sqlite:///" + _TMP.replace("\\", "/")
os.environ["MBS_SECRET"] = "test-secret"
os.environ.setdefault("MBS_ADMIN_PASSWORD", "manager")

import pytest                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

from app.db import Base, engine                  # noqa: E402
from app.main import app, boot                   # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    boot()  # mints the first manager on an empty database
    with TestClient(app) as test_client:
        yield test_client


def sign_in(client, email: str, password: str) -> dict:
    """Returns the Authorization header for that account."""
    reply = client.post("/auth/login", json={"email": email, "password": password})
    assert reply.status_code == 200, reply.text
    return {"Authorization": "Bearer " + reply.json()["token"]}


@pytest.fixture()
def manager(client):
    return sign_in(client, "manager@mbs.co", "manager")
