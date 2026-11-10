"""First-run setup, sign-in and secret handling."""

import json
import stat

from app import main, vault
from app.config import get_settings
from tests.conftest import PASSWORD, USER

SETUP = {"name": USER, "password": PASSWORD, "anthropic_key": "sk-secret",
         "github_token": "ghp-secret"}


def test_fresh_install_reports_it_needs_setup(anonymous):
    assert anonymous.get("/api/health").json() == {
        "status": "ok", "configured": False,
        "needs": {"anthropic_key": True, "github_token": True},
    }
    assert anonymous.get("/api/overview").status_code == 401


def test_setup_stores_secrets_privately_and_locks(anonymous):
    resp = anonymous.post("/api/setup", json=SETUP)
    assert resp.status_code == 201 and "secret" not in resp.text
    path = get_settings().data_dir / "secrets.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["anthropic_api_key"] == "sk-secret"
    assert anonymous.post("/api/setup", json=SETUP).status_code == 409
    assert anonymous.get("/api/health").json()["configured"] is True


def test_setup_refuses_credentials_the_services_reject(anonymous, monkeypatch):
    monkeypatch.setattr(main, "check_key", lambda k, m: "Anthropic rejected this API key")
    resp = anonymous.post("/api/setup", json=SETUP)
    assert resp.status_code == 422 and "rejected" in resp.json()["detail"]
    assert anonymous.get("/api/health").json()["configured"] is False
    assert not vault.anthropic_key()


def test_setup_requires_both_credentials(anonymous):
    resp = anonymous.post("/api/setup", json={**SETUP, "github_token": ""})
    assert resp.status_code == 422


def test_login_logout(anonymous):
    anonymous.post("/api/setup", json=SETUP)
    bad = anonymous.post("/api/auth/login", json={"name": USER, "password": "wrong-password"})
    assert bad.status_code == 401
    ok = anonymous.post("/api/auth/login", json={"name": USER.lower(), "password": PASSWORD})
    assert ok.status_code == 200
    headers = {"Authorization": f"Bearer {ok.json()['token']}"}
    assert anonymous.get("/api/me", headers=headers).json() == {"name": USER}
    anonymous.post("/api/auth/logout", headers=headers)
    assert anonymous.get("/api/me", headers=headers).status_code == 401


def test_repeated_failed_logins_are_throttled(anonymous):
    anonymous.post("/api/setup", json=SETUP)
    body = {"name": "throttled-user", "password": "x"}
    codes = [anonymous.post("/api/auth/login", json=body).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_second_approver_signs_under_their_own_name(client):
    assert client.post("/api/users", json={"name": "Ravi", "password": "another-pass"}).is_success
    assert client.post("/api/users", json={"name": "ravi", "password": "another-pass"}).status_code == 409
    login = client.post("/api/auth/login", json={"name": "Ravi", "password": "another-pass"})
    me = client.get("/api/me", headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert me.json() == {"name": "Ravi"}


def test_settings_never_return_secrets(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200 and "sk-x" not in resp.text and "ghp-x" not in resp.text
    github = resp.json()["github"]
    assert (github["ok"], github["login"], github["mode"]) == (True, "asha", "token")


def test_updating_credentials_is_audited_without_the_value(client):
    assert client.put("/api/settings/credentials", json={"github_token": "ghp-new"}).is_success
    events = client.get("/api/audit?action=settings.").json()["events"]
    assert events[0]["data"] == {"anthropic": False, "github": True}
    assert "ghp-new" not in str(events)
