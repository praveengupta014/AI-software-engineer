import builtins
import getpass

import pytest

from app import reset_password
from tests.conftest import PASSWORD, USER

NEW = "a brand new password"


def login(client, password):
    return client.post("/api/auth/login", json={"name": USER, "password": password}).status_code


def typed(monkeypatch, *answers):
    values = iter(answers)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(values))


def test_reset_changes_password_ends_sessions_and_is_audited(client, monkeypatch):
    typed(monkeypatch, NEW, NEW)
    assert reset_password.main([]) == 0

    assert client.get("/api/me").status_code == 401  # the old session is gone
    assert login(client, PASSWORD) == 401
    token = client.post("/api/auth/login", json={"name": USER, "password": NEW}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"

    events = client.get("/api/audit?action=auth.password_reset").json()["events"]
    assert events[0]["actor"] == "command-line" and events[0]["subject_id"] == USER
    assert NEW not in str(events)
    assert client.get("/api/audit/verify").json()["ok"] is True


@pytest.mark.parametrize("answers", [("short", "short"), (NEW, "something else")])
def test_bad_input_changes_nothing(client, monkeypatch, answers, capsys):
    typed(monkeypatch, *answers)
    assert reset_password.main([]) == 1
    assert "Nothing was changed" in capsys.readouterr().out
    assert client.get("/api/me").status_code == 200
    assert login(client, PASSWORD) == 200


def test_choosing_between_accounts(client, monkeypatch):
    client.post("/api/users", json={"name": "Ravi", "password": "another-pass"})
    monkeypatch.setattr(builtins, "input", lambda prompt="": "2")
    typed(monkeypatch, NEW, NEW)
    assert reset_password.main([]) == 0
    assert client.post("/api/auth/login", json={"name": "Ravi", "password": NEW}).status_code == 200
    assert login(client, PASSWORD) == 200


def test_invalid_account_choice(client, monkeypatch):
    client.post("/api/users", json={"name": "Ravi", "password": "another-pass"})
    monkeypatch.setattr(builtins, "input", lambda prompt="": "9")
    assert reset_password.main([]) == 1


def test_missing_data_folder_is_explained(anonymous, monkeypatch, tmp_path, capsys):
    from app.config import get_settings

    monkeypatch.setenv("COUNTERSIGN_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.delenv("COUNTERSIGN_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    assert reset_password.main([]) == 1
    assert "Run this from the backend folder" in capsys.readouterr().out


def test_generated_password_signs_in(client, capsys):
    assert reset_password.main(["--generate"]) == 0
    out = capsys.readouterr().out
    password = next(
        line.split()[-1] for line in out.splitlines() if line.strip().startswith("Password:")
    )
    assert f"Account name:  {USER}" in out and len(password) == 19
    assert login(client, PASSWORD) == 401
    assert login(client, password) == 200
