"""GitHub REST client. Read methods are used by agents through RepoView; the two write
methods (open_pull_request, post_review) are called only from pipeline._execute_external,
which requires an approved proposal."""

import re
import threading
import time
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import jwt


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


class GitHub(Protocol):
    def viewer(self) -> dict[str, Any]: ...
    def repos(self) -> list[dict[str, Any]]: ...
    def branches(self, repo: str) -> list[str]: ...
    def open_pulls(self, repo: str) -> list[dict[str, Any]]: ...
    def branch_sha(self, repo: str, branch: str) -> str: ...
    def tree(self, repo: str, sha: str) -> dict[str, Any]: ...
    def file_text(self, repo: str, path: str, ref: str) -> str | None: ...
    def pull(self, repo: str, number: int) -> dict[str, Any]: ...
    def pull_files(self, repo: str, number: int) -> list[dict[str, Any]]: ...
    def open_pull_request(self, repo: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def post_review(
        self, repo: str, number: int, commit_sha: str, body: str, comments: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "countersign-agent",
            },
        )

    def _auth(self, url: str) -> dict[str, str]:
        return {}

    def _request(self, method: str, url: str, *, ok_404: bool = False, **kw) -> httpx.Response:
        headers = kw.get("headers", {})
        kw["headers"] = headers if "Authorization" in headers else {**self._auth(url), **headers}
        resp = self._http.request(method, url, **kw)
        if resp.status_code >= 400 and not (ok_404 and resp.status_code == 404):
            try:
                message = resp.json().get("message", resp.text)
            except ValueError:
                message = resp.text
            raise GitHubError(resp.status_code, str(message)[:500])
        return resp

    def viewer(self) -> dict[str, Any]:
        data = self._request("GET", "/user").json()
        return {"login": data["login"], "avatar_url": data.get("avatar_url", "")}

    def repos(self) -> list[dict[str, Any]]:
        """Repositories this token can push to, most recently active first."""
        data = self._request(
            "GET",
            "/user/repos",
            params={"per_page": 100, "sort": "pushed",
                    "affiliation": "owner,collaborator,organization_member"},
        ).json()
        return [
            {
                "full_name": r["full_name"],
                "default_branch": r["default_branch"],
                "private": r["private"],
                "description": r.get("description") or "",
            }
            for r in data
            if r.get("permissions", {}).get("push")
        ]

    def branches(self, repo: str) -> list[str]:
        data = self._request(
            "GET", f"/repos/{repo}/branches", params={"per_page": 100}
        ).json()
        return [b["name"] for b in data]

    def open_pulls(self, repo: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET", f"/repos/{repo}/pulls",
            params={"state": "open", "per_page": 50, "sort": "updated", "direction": "desc"},
        ).json()
        return [
            {"number": d["number"], "title": d["title"], "author": d["user"]["login"]}
            for d in data
        ]

    def branch_sha(self, repo: str, branch: str) -> str:
        ref = quote(branch, safe="/")
        return self._request("GET", f"/repos/{repo}/git/ref/heads/{ref}").json()["object"]["sha"]

    def tree(self, repo: str, sha: str) -> dict[str, Any]:
        data = self._request("GET", f"/repos/{repo}/git/trees/{sha}?recursive=1").json()
        entries = [
            {"path": e["path"], "size": e.get("size", 0), "mode": e["mode"]}
            for e in data["tree"]
            if e["type"] == "blob"
        ]
        return {"entries": entries, "truncated": data.get("truncated", False)}

    def file_text(self, repo: str, path: str, ref: str) -> str | None:
        resp = self._request(
            "GET",
            f"/repos/{repo}/contents/{quote(path)}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw+json"},
            ok_404=True,
        )
        if resp.status_code == 404:
            return None
        try:
            return resp.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubError(415, f"{path} is not UTF-8 text") from exc

    def pull(self, repo: str, number: int) -> dict[str, Any]:
        d = self._request("GET", f"/repos/{repo}/pulls/{number}").json()
        return {
            "number": d["number"],
            "title": d["title"],
            "body": d.get("body") or "",
            "state": d["state"],
            "author": d["user"]["login"],
            "url": d["html_url"],
            "head_sha": d["head"]["sha"],
            "base_ref": d["base"]["ref"],
            "head_ref": d["head"]["ref"],
        }

    def pull_files(self, repo: str, number: int) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/repos/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            ).json()
            files += [
                {
                    "path": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "patch": f.get("patch"),
                }
                for f in batch
            ]
            if len(batch) < 100:
                return files
            page += 1

    def open_pull_request(self, repo: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Commit the approved files on a new branch from base_sha and open a PR.

        Safe to retry after a partial failure: the branch is moved to the new commit and an
        existing PR for it is reused. Branching from the recorded base_sha means a base that
        moved on shows up as a normal merge conflict rather than being silently overwritten.
        """
        head = payload["head_branch"]
        if not head.startswith("countersign/"):
            raise GitHubError(422, f"refusing to write to non-countersign branch {head}")
        base_sha = payload["base_sha"]
        base_tree = self._request("GET", f"/repos/{repo}/git/commits/{base_sha}").json()["tree"]
        modes = {e["path"]: e["mode"] for e in self.tree(repo, base_sha)["entries"]}

        items = []
        for f in payload["files"]:
            item = {"path": f["path"], "mode": modes.get(f["path"], "100644"), "type": "blob"}
            if f["action"] == "delete":
                item["sha"] = None
            else:
                item["content"] = f["content"]
            items.append(item)

        tree = self._request(
            "POST", f"/repos/{repo}/git/trees", json={"base_tree": base_tree["sha"], "tree": items}
        ).json()
        commit = self._request(
            "POST",
            f"/repos/{repo}/git/commits",
            json={
                "message": payload["commit_message"],
                "tree": tree["sha"],
                "parents": [base_sha],
            },
        ).json()

        try:
            self._request(
                "POST",
                f"/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{head}", "sha": commit["sha"]},
            )
        except GitHubError as exc:
            if exc.status != 422:
                raise
            self._request(
                "PATCH",
                f"/repos/{repo}/git/refs/heads/{quote(head, safe='/')}",
                json={"sha": commit["sha"], "force": True},
            )

        owner = repo.split("/")[0]
        try:
            pr = self._request(
                "POST",
                f"/repos/{repo}/pulls",
                json={
                    "title": payload["title"],
                    "body": payload["body"],
                    "head": head,
                    "base": payload["base_branch"],
                },
            ).json()
        except GitHubError as exc:
            if exc.status != 422:
                raise
            existing = self._request(
                "GET",
                f"/repos/{repo}/pulls",
                params={"head": f"{owner}:{head}", "state": "open"},
            ).json()
            if not existing:
                raise
            pr = existing[0]
        return {"number": pr["number"], "url": pr["html_url"], "commit_sha": commit["sha"]}

    def post_review(
        self, repo: str, number: int, commit_sha: str, body: str, comments: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Always posts as COMMENT. Countersign never formally approves or blocks a PR, and
        GitHub would refuse APPROVE from the account that opened it anyway."""
        data = self._request(
            "POST",
            f"/repos/{repo}/pulls/{number}/reviews",
            json={
                "commit_id": commit_sha,
                "body": body,
                "event": "COMMENT",
                "comments": [
                    {"path": c["path"], "line": c["line"], "side": "RIGHT", "body": c["body"]}
                    for c in comments
                ],
            },
        ).json()
        return {"url": data.get("html_url", "")}


def check_token(token: str, base_url: str) -> tuple[str | None, str | None]:
    """Returns (github_login, problem)."""
    try:
        return GitHubClient(token, base_url).viewer()["login"], None
    except GitHubError as exc:
        if exc.status == 401:
            return None, "GitHub rejected this token"
        return None, str(exc)
    except httpx.HTTPError:
        return None, "Could not reach GitHub. Check the server's internet connection."


class GitHubAppClient(GitHubClient):
    """Authenticates as a GitHub App: a short-lived token per installation instead of one
    person's long-lived token, and commits appear under the app's own name."""

    _TOKEN_MARGIN_SECONDS = 300

    def __init__(self, app_id: str, private_key: str, base_url: str = "https://api.github.com"):
        super().__init__("", base_url)
        self._http.headers.pop("Authorization", None)
        self._app_id, self._private_key = app_id, private_key
        self._lock = threading.Lock()
        self._installations: dict[str, int] = {}
        self._tokens: dict[int, tuple[str, float]] = {}

    def _app_jwt(self) -> str:
        now = int(time.time())
        claims = {"iat": now - 60, "exp": now + 540, "iss": self._app_id}
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    def _app_request(self, method: str, url: str, **kw) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._app_jwt()}"}
        return GitHubClient._request(self, method, url, headers=headers, **kw)

    def _installation_token(self, installation_id: int) -> str:
        with self._lock:
            cached = self._tokens.get(installation_id)
            if cached and cached[1] > time.time():
                return cached[0]
        data = self._app_request(
            "POST", f"/app/installations/{installation_id}/access_tokens"
        ).json()
        with self._lock:
            # GitHub issues these for an hour; the margin avoids using one as it expires.
            self._tokens[installation_id] = (
                data["token"], time.time() + 3600 - self._TOKEN_MARGIN_SECONDS,
            )
        return data["token"]

    def _installation_for(self, repo: str) -> int:
        with self._lock:
            if repo in self._installations:
                return self._installations[repo]
        try:
            installation_id = self._app_request("GET", f"/repos/{repo}/installation").json()["id"]
        except GitHubError as exc:
            if exc.status == 404:
                raise GitHubError(404, f"The GitHub App is not installed on {repo}") from exc
            raise
        with self._lock:
            self._installations[repo] = installation_id
        return installation_id

    def _auth(self, url: str) -> dict[str, str]:
        match = re.match(r"^/repos/([^/]+/[^/]+)", url)
        if not match:
            return {}
        token = self._installation_token(self._installation_for(match.group(1)))
        return {"Authorization": f"Bearer {token}"}

    def viewer(self) -> dict[str, Any]:
        data = self._app_request("GET", "/app").json()
        return {"login": f"{data['slug']}[bot]", "avatar_url": "", "slug": data["slug"]}

    def repos(self) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        installations = self._app_request(
            "GET", "/app/installations", params={"per_page": 100}
        ).json()
        for installation in installations:
            token = self._installation_token(installation["id"])
            page = 1
            while True:
                batch = GitHubClient._request(
                    self, "GET", "/installation/repositories",
                    params={"per_page": 100, "page": page},
                    headers={"Authorization": f"Bearer {token}"},
                ).json()["repositories"]
                repositories += [
                    {
                        "full_name": r["full_name"],
                        "default_branch": r["default_branch"],
                        "private": r["private"],
                        "description": r.get("description") or "",
                    }
                    for r in batch
                ]
                if len(batch) < 100:
                    break
                page += 1
        return repositories


def check_app(
    app_id: str, private_key: str, base_url: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (app details, problem)."""
    try:
        client = GitHubAppClient(app_id, private_key, base_url)
        return client.viewer(), None
    except (jwt.PyJWTError, ValueError, TypeError):
        return None, "That private key could not be used. Paste the whole .pem file."
    except GitHubError as exc:
        if exc.status == 401:
            return None, "GitHub rejected this App ID and private key"
        return None, str(exc)
    except httpx.HTTPError:
        return None, "Could not reach GitHub. Check the server's internet connection."


class RepoView:
    """Read-only window on a repo at one commit, optionally with approved-but-unmerged
    changes layered on top. This is the only GitHub access an agent gets."""

    MAX_READ_BYTES = 400_000

    def __init__(
        self, gh: GitHub, repo: str, ref: str, overlay: dict[str, str | None] | None = None
    ):
        self._gh, self.repo, self.ref = gh, repo, ref
        self.overlay = overlay or {}
        self._tree: dict[str, Any] | None = None

    def _load_tree(self) -> dict[str, Any]:
        if self._tree is None:
            self._tree = self._gh.tree(self.repo, self.ref)
        return self._tree

    def paths(self) -> list[str]:
        paths = {e["path"] for e in self._load_tree()["entries"]}
        for path, content in self.overlay.items():
            if content is None:
                paths.discard(path)
            else:
                paths.add(path)
        return sorted(paths)

    def list_files(self, prefix: str = "") -> str:
        matched = [p for p in self.paths() if p.startswith(prefix)]
        note = ""
        if self._load_tree()["truncated"]:
            note = "\n[GitHub truncated this tree: some files are not listed]"
        return ("\n".join(matched) or "(no files match)") + note

    def exists(self, path: str) -> bool:
        return path in self.paths()

    def read(self, path: str) -> str | None:
        if path in self.overlay:
            return self.overlay[path]
        return self._gh.file_text(self.repo, path, self.ref)
