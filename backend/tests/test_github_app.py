import json

import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import main, vault
from app.github_client import GitHubAppClient, GitHubError, check_app

API = "https://api.github.com"
REPO = "o/r"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = _key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


def bearer(call):
    return call.request.headers["Authorization"].removeprefix("Bearer ")


def mock_installation():
    lookup = respx.get(f"{API}/repos/{REPO}/installation").respond(json={"id": 7})
    tokens = respx.post(f"{API}/app/installations/7/access_tokens").respond(
        status_code=201, json={"token": "inst-token", "expires_at": "2099-01-01T00:00:00Z"}
    )
    return lookup, tokens


@respx.mock
def test_repo_calls_use_a_short_lived_installation_token():
    lookup, _ = mock_installation()
    ref = respx.get(f"{API}/repos/{REPO}/git/ref/heads/main").respond(
        json={"object": {"sha": "abc"}}
    )
    client = GitHubAppClient("123", PEM)
    assert client.branch_sha(REPO, "main") == "abc"

    claims = jwt.decode(bearer(lookup.calls[0]), _key.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "123" and claims["exp"] - claims["iat"] <= 600
    assert bearer(ref.calls[0]) == "inst-token"


@respx.mock
def test_token_is_reused_rather_than_requested_per_call():
    _, tokens = mock_installation()
    respx.get(f"{API}/repos/{REPO}/git/ref/heads/main").respond(json={"object": {"sha": "a"}})
    client = GitHubAppClient("123", PEM)
    client.branch_sha(REPO, "main")
    client.branch_sha(REPO, "main")
    assert tokens.call_count == 1


@respx.mock
def test_expired_token_is_replaced():
    _, tokens = mock_installation()
    respx.get(f"{API}/repos/{REPO}/git/ref/heads/main").respond(json={"object": {"sha": "a"}})
    client = GitHubAppClient("123", PEM)
    client.branch_sha(REPO, "main")
    client._tokens[7] = ("old", 0.0)
    client.branch_sha(REPO, "main")
    assert tokens.call_count == 2


@respx.mock
def test_clear_error_when_app_is_not_installed():
    respx.get(f"{API}/repos/{REPO}/installation").respond(
        status_code=404, json={"message": "Not Found"}
    )
    with pytest.raises(GitHubError, match="not installed on o/r"):
        GitHubAppClient("123", PEM).branch_sha(REPO, "main")


@respx.mock
def test_repos_spans_every_installation():
    respx.get(f"{API}/app/installations").respond(json=[{"id": 7}, {"id": 8}])
    for installation in (7, 8):
        respx.post(f"{API}/app/installations/{installation}/access_tokens").respond(
            status_code=201, json={"token": f"t{installation}"}
        )

    def repositories(request):
        name = "a" if "t7" in request.headers["Authorization"] else "b"
        import httpx

        return httpx.Response(200, json={"repositories": [
            {"full_name": f"o/{name}", "default_branch": "main", "private": True,
             "description": None},
        ]})

    respx.get(f"{API}/installation/repositories").mock(side_effect=repositories)
    assert [r["full_name"] for r in GitHubAppClient("123", PEM).repos()] == ["o/a", "o/b"]


@respx.mock
def test_check_app_reports_identity_and_failures():
    route = respx.get(f"{API}/app").respond(json={"slug": "countersign-acme"})
    assert check_app("123", PEM, API) == (
        {"login": "countersign-acme[bot]", "avatar_url": "", "slug": "countersign-acme"}, None
    )
    route.respond(status_code=401, json={"message": "bad"})
    assert check_app("123", PEM, API) == (None, "GitHub rejected this App ID and private key")


def test_check_app_explains_an_unusable_key():
    details, problem = check_app("123", "not a key", API)
    assert details is None and "whole .pem file" in problem


def test_connecting_an_app_never_returns_the_key(client, monkeypatch):
    from tests.fakes import FakeGitHub

    monkeypatch.setattr(main, "check_app", lambda a, k, u: ({
        "login": "x[bot]", "avatar_url": "", "slug": "x"}, None))
    resp = client.put("/api/settings/github-app", json={
        "app_id": "123", "private_key": PEM, "webhook_secret": "whsec",
    })
    assert resp.status_code == 200
    assert vault.github_app() == ("123", PEM.strip())
    assert vault.github_webhook_secret() == "whsec"

    from app.pipeline import backends

    assert isinstance(backends.github, GitHubAppClient)
    backends.github = FakeGitHub()
    settings = client.get("/api/settings")
    assert "BEGIN PRIVATE KEY" not in settings.text and "whsec" not in settings.text
    body = settings.json()
    assert body["github"]["mode"] == "app"
    assert body["github"]["install_url"] == "https://github.com/apps/x/installations/new"
    assert body["webhooks"]["configured"] is True

    events = json.dumps(client.get("/api/audit?action=settings.").json())
    assert "BEGIN PRIVATE KEY" not in events and "whsec" not in events


def test_a_rejected_app_is_not_stored(client, monkeypatch):
    monkeypatch.setattr(main, "check_app", lambda a, k, u: (None, "GitHub rejected this"))
    resp = client.put("/api/settings/github-app", json={"app_id": "1", "private_key": PEM})
    assert resp.status_code == 422 and vault.github_app() is None
