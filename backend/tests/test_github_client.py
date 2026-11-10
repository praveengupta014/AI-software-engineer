import json

import httpx
import pytest
import respx

from app.github_client import GitHubClient, GitHubError, check_token
from app.safety import commentable_lines, path_problem, risk_flags

API = "https://api.github.com"
REPO = "o/r"


def payload(**over):
    return {
        "title": "T", "body": "B", "commit_message": "M", "base_branch": "main",
        "base_sha": "base", "head_branch": "countersign/abc-x",
        "files": [
            {"path": "new.py", "action": "create", "content": "x"},
            {"path": "run.sh", "action": "update", "content": "y"},
            {"path": "old.py", "action": "delete", "content": ""},
        ],
        **over,
    }


def mock_common():
    respx.get(f"{API}/repos/{REPO}/git/commits/base").respond(
        json={"tree": {"sha": "basetree"}})
    respx.get(f"{API}/repos/{REPO}/git/trees/base?recursive=1").respond(json={"tree": [
        {"path": "run.sh", "type": "blob", "mode": "100755", "size": 1},
        {"path": "old.py", "type": "blob", "mode": "100644", "size": 1},
    ]})
    tree = respx.post(f"{API}/repos/{REPO}/git/trees").respond(json={"sha": "newtree"})
    commit = respx.post(f"{API}/repos/{REPO}/git/commits").respond(json={"sha": "newcommit"})
    return tree, commit


@respx.mock
def test_open_pr_commits_files_preserving_modes():
    tree, commit = mock_common()
    respx.post(f"{API}/repos/{REPO}/git/refs").respond(status_code=201, json={})
    pulls = respx.post(f"{API}/repos/{REPO}/pulls").respond(
        status_code=201, json={"number": 7, "html_url": "u"})

    result = GitHubClient("t").open_pull_request(REPO, payload())

    assert result == {"number": 7, "url": "u", "commit_sha": "newcommit"}
    sent = json.loads(tree.calls[0].request.content)
    assert sent["base_tree"] == "basetree"
    assert {i["path"]: i["mode"] for i in sent["tree"]}["run.sh"] == "100755"
    assert next(i for i in sent["tree"] if i["path"] == "old.py")["sha"] is None
    assert json.loads(commit.calls[0].request.content)["parents"] == ["base"]
    assert json.loads(pulls.calls[0].request.content)["head"] == "countersign/abc-x"


@respx.mock
def test_retry_moves_existing_branch_and_reuses_open_pr():
    mock_common()
    respx.post(f"{API}/repos/{REPO}/git/refs").respond(
        status_code=422, json={"message": "Reference already exists"})
    patch = respx.patch(f"{API}/repos/{REPO}/git/refs/heads/countersign/abc-x").respond(json={})
    respx.post(f"{API}/repos/{REPO}/pulls").respond(
        status_code=422, json={"message": "A pull request already exists"})
    respx.get(f"{API}/repos/{REPO}/pulls").respond(json=[{"number": 7, "html_url": "u"}])

    assert GitHubClient("t").open_pull_request(REPO, payload())["number"] == 7
    assert patch.called


def test_refuses_to_write_outside_countersign_branches():
    with pytest.raises(GitHubError, match="non-countersign"):
        GitHubClient("t").open_pull_request(REPO, payload(head_branch="main"))


@respx.mock
def test_error_message_is_surfaced():
    respx.get(f"{API}/repos/{REPO}/git/ref/heads/main").respond(
        status_code=404, json={"message": "Not Found"})
    with pytest.raises(GitHubError, match="404: Not Found"):
        GitHubClient("t").branch_sha(REPO, "main")


@respx.mock
def test_token_is_only_sent_to_github():
    route = respx.get(f"{API}/repos/{REPO}/git/ref/heads/main").respond(
        json={"object": {"sha": "abc"}})
    GitHubClient("secret").branch_sha(REPO, "main")
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret"


@pytest.mark.parametrize("path", ["../x", "a/../b", "/etc/passwd", ".git/config", "a\\b", "", " a"])
def test_bad_paths(path):
    assert path_problem(path)


@pytest.mark.parametrize("path", ["a.py", "src/a.py", ".github/workflows/ci.yml", "a..b/c"])
def test_good_paths(path):
    assert path_problem(path) is None


def test_commentable_lines_track_new_file_numbers():
    patch = "@@ -10,3 +20,4 @@ def f():\n ctx\n-old\n+new\n+new2\n ctx2\n\\ No newline at end"
    assert commentable_lines(patch) == {20, 21, 22, 23}
    assert commentable_lines(None) == set()


def test_risk_flags():
    flags = risk_flags([
        {"path": ".github/workflows/ci.yml", "action": "update", "content": "on: push"},
        {"path": "requirements.txt", "action": "update", "content": "x"},
        {"path": "old.py", "action": "delete", "content": ""},
    ])
    assert {f["code"]: f["level"] for f in flags} == {
        "ci_change": "high", "dependency_change": "medium", "file_deleted": "medium",
    }


def test_timeouts_are_not_swallowed():
    with respx.mock:
        respx.get(f"{API}/repos/{REPO}/git/ref/heads/main").mock(
            side_effect=httpx.ConnectTimeout("x"))
        with pytest.raises(httpx.HTTPError):
            GitHubClient("t").branch_sha(REPO, "main")


@respx.mock
def test_repos_only_lists_what_the_token_can_push_to():
    respx.get(f"{API}/user/repos").respond(json=[
        {"full_name": "o/mine", "default_branch": "main", "private": True, "description": None,
         "permissions": {"push": True}},
        {"full_name": "o/theirs", "default_branch": "main", "private": False,
         "description": "", "permissions": {"push": False}},
    ])
    assert [r["full_name"] for r in GitHubClient("t").repos()] == ["o/mine"]


@respx.mock
def test_check_token_reports_rejection():
    respx.get(f"{API}/user").respond(status_code=401, json={"message": "Bad credentials"})
    assert check_token("bad", API) == (None, "GitHub rejected this token")


def test_github_outage_is_a_clean_error_not_a_crash(client, monkeypatch):
    from app import pipeline

    def down():
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(pipeline.backends.github, "repos", down, raising=False)
    resp = client.get("/api/github/repos")
    assert resp.status_code == 502 and resp.json() == {"detail": "Could not reach GitHub. Try again."}
