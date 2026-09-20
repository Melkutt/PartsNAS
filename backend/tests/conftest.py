"""Test setup: every test run gets its own empty data dir, so the real database is never touched.

The app builds its engine when `app.main` is imported, so the environment has to be
pointed at the temp dir *before* that import.
"""
import os
import sys
import tempfile
from pathlib import Path

_DATA = tempfile.mkdtemp(prefix="partsnas-test-")
os.environ["PARTSNAS_DATA_DIR"] = _DATA
os.environ.pop("PARTSNAS_API_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:  # the context manager runs startup: tables + seed data
        yield c


@pytest.fixture()
def part(client):
    """A throw-away part, deleted again afterwards."""
    r = client.post("/api/parts", json={"name": "ZZ_TEST part", "mpn": "ZZ_TEST_MPN", "min_stock": 2})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    yield pid
    client.delete(f"/api/parts/{pid}")
