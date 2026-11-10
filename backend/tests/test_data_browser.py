"""The Data page must show what is stored without ever exposing credentials."""

import pytest

from tests.conftest import PASSWORD
from tests.fakes import DEMO_REPO

REQ = {"title": "Rate limit login", "body": "Stop password guessing on login.", "repo": DEMO_REPO}


def test_requires_sign_in(anonymous):
    assert anonymous.get("/api/data").status_code == 401
    assert anonymous.get("/api/data/users").status_code == 401


def test_summary_counts_tables_and_reports_location(client):
    client.post("/api/requirements", json=REQ)
    body = client.get("/api/data").json()
    counts = {t["key"]: t["count"] for t in body["tables"]}
    assert counts["requirements"] == 1 and counts["users"] == 1 and counts["agent_runs"] == 1
    storage = body["storage"]
    assert storage["path"] and storage["size_bytes"] > 0 and storage["kind"] in ("sqlite", "postgresql")
    assert "@" not in storage["path"] and "test@" not in str(body)  # never the connection password


def test_credentials_never_appear(client):
    tables = [t["key"] for t in client.get("/api/data").json()["tables"]]
    assert "sessions" not in tables
    assert client.get("/api/data/sessions").status_code == 404
    assert client.get("/api/data/secrets").status_code == 404

    listing = client.get("/api/data/users")
    assert "password_hash" not in listing.json()["columns"]
    row_id = listing.json()["rows"][0]["id"]
    detail = client.get(f"/api/data/users/{row_id}")
    assert detail.status_code == 200 and "password_hash" not in detail.json()
    assert PASSWORD not in detail.text and "$" not in detail.text


def test_hash_cannot_be_probed_through_search(client):
    from app.db import read_session
    from app.models import User

    with read_session() as s:
        stored = s.query(User).first().password_hash
    assert client.get("/api/data/users", params={"q": stored[:12]}).json()["total"] == 0


def test_long_fields_only_load_in_detail(client):
    client.post("/api/requirements", json=REQ)
    listing = client.get("/api/data/proposals").json()
    assert "payload" not in listing["columns"]
    detail = client.get(f"/api/data/proposals/{listing['rows'][0]['id']}").json()
    assert detail["payload"]["tasks"]


def test_search_covers_text_and_json_and_treats_wildcards_literally(client):
    client.post("/api/requirements", json=REQ)
    assert client.get("/api/data/requirements", params={"q": "RATE LIMIT"}).json()["total"] == 1
    assert client.get("/api/data/requirements", params={"q": "nothing"}).json()["total"] == 0
    assert client.get("/api/data/requirements", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/data/requirements", params={"q": "_"}).json()["total"] == 0
    events = client.get("/api/data/audit_events", params={"q": "list_files"}).json()
    assert events["total"] >= 1


def test_pagination_is_newest_first(client):
    for _ in range(3):
        client.post("/api/requirements", json=REQ)
    first = client.get("/api/data/audit_events").json()
    assert first["page_size"] == 25 and first["total"] > 25
    seqs = [r["seq"] for r in first["rows"]]
    assert seqs == sorted(seqs, reverse=True)
    second = client.get("/api/data/audit_events", params={"page": 2}).json()
    assert second["rows"][0]["seq"] == seqs[-1] - 1


def test_audit_rows_use_numeric_ids(client):
    client.post("/api/requirements", json=REQ)
    assert client.get("/api/data/audit_events/1").json()["seq"] == 1
    assert client.get("/api/data/audit_events/abc").status_code == 404
    assert client.get("/api/data/audit_events/999999").status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_the_data_api_is_read_only(client, method):
    assert getattr(client, method)("/api/data/requirements").status_code == 405
