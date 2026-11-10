"""Test doubles: a scripted model and an in-memory GitHub. The real agent loop, safety
checks, approvals and audit trail all run on top of them."""

import difflib
import re
import threading
import time
from typing import Any

from app.audit import sha256_hex
from app.github_client import GitHubError
from app.llm import ToolCall, Turn

DEMO_REPO = "acme/storefront"
DEMO_SHA = "d3m0" + "0" * 36

_FILES = {
    "README.md": "# Storefront API\n\nA small FastAPI service for the Acme storefront.\n",
    "requirements.txt": "fastapi==0.115.0\nuvicorn==0.30.0\npytest==8.3.0\n",
    "app/__init__.py": "",
    "app/auth.py": (
        "USERS = {\"ada\": \"correct-horse\"}\n\n\n"
        "def check_password(username: str, password: str) -> bool:\n"
        "    return USERS.get(username) == password\n"
    ),
    "app/main.py": (
        "from fastapi import FastAPI, HTTPException\n\n"
        "from app.auth import check_password\n\n"
        "app = FastAPI()\n\n\n"
        "@app.post(\"/login\")\n"
        "def login(username: str, password: str):\n"
        "    if not check_password(username, password):\n"
        "        raise HTTPException(status_code=401, detail=\"Invalid credentials\")\n"
        "    return {\"ok\": True}\n"
    ),
    "tests/test_auth.py": (
        "from app.auth import check_password\n\n\n"
        "def test_valid_password():\n"
        "    assert check_password(\"ada\", \"correct-horse\")\n"
    ),
}

_LIMITER = """import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    \"\"\"Sliding-window limiter: at most `limit` hits per key in `window` seconds.\"\"\"

    def __init__(self, limit: int = 5, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True
"""

_LIMITER_TESTS = """from app.rate_limit import RateLimiter


def test_allows_up_to_the_limit():
    limiter = RateLimiter(limit=2, window=60)
    assert limiter.allow("ada")
    assert limiter.allow("ada")
    assert not limiter.allow("ada")


def test_keys_are_independent():
    limiter = RateLimiter(limit=1, window=60)
    assert limiter.allow("ada")
    assert limiter.allow("grace")


def test_hits_expire_after_the_window():
    limiter = RateLimiter(limit=1, window=0)
    assert limiter.allow("ada")
    assert limiter.allow("ada")
"""

_LOGIN_PATCHED = _FILES["app/main.py"].replace(
    "from app.auth import check_password\n",
    "from app.auth import check_password\nfrom app.rate_limit import RateLimiter\n",
).replace(
    "app = FastAPI()\n",
    "app = FastAPI()\nlogin_limiter = RateLimiter(limit=5, window=60)\n",
).replace(
    "def login(username: str, password: str):\n",
    "def login(username: str, password: str):\n"
    "    if not login_limiter.allow(username):\n"
    "        raise HTTPException(status_code=429, detail=\"Too many attempts\")\n",
)


class FakeGitHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_pr = 101
        self.pulls: dict[int, dict[str, Any]] = {}
        self.pull_patches: dict[int, list[dict[str, Any]]] = {}
        self.reviews: list[dict[str, Any]] = []
        self._seed_pull()

    def _seed_pull(self) -> None:
        self.pulls[42] = {
            "number": 42,
            "title": "Normalise usernames before password check",
            "body": "Lower-cases usernames at login.",
            "state": "open",
            "author": "grace",
            "url": "https://github.example/acme/storefront/pull/42",
            "head_sha": "feed" + "0" * 36,
            "base_ref": "main",
            "head_ref": "normalise-usernames",
        }
        changed = _FILES["app/auth.py"].replace(
            "    return USERS.get(username) == password\n",
            "    return USERS.get(username.lower()) == password\n",
        )
        self.pull_patches[42] = [self._patch("app/auth.py", _FILES["app/auth.py"], changed)]

    @staticmethod
    def _patch(path: str, old: str, new: str) -> dict[str, Any]:
        lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""))[2:]
        return {
            "path": path,
            "status": "added" if not old else "modified",
            "additions": sum(1 for x in lines if x.startswith("+")),
            "deletions": sum(1 for x in lines if x.startswith("-")),
            "patch": "\n".join(lines),
        }

    @staticmethod
    def _check(repo: str) -> None:
        if repo != DEMO_REPO:
            raise GitHubError(404, f"Test GitHub only has {DEMO_REPO}")

    def branch_sha(self, repo: str, branch: str) -> str:
        self._check(repo)
        return DEMO_SHA

    def tree(self, repo: str, sha: str) -> dict[str, Any]:
        self._check(repo)
        entries = [{"path": p, "size": len(c), "mode": "100644"} for p, c in _FILES.items()]
        return {"entries": entries, "truncated": False}

    def file_text(self, repo: str, path: str, ref: str) -> str | None:
        self._check(repo)
        return _FILES.get(path)

    def pull(self, repo: str, number: int) -> dict[str, Any]:
        self._check(repo)
        if number not in self.pulls:
            raise GitHubError(404, f"Test GitHub has no PR #{number}")
        return self.pulls[number]

    def pull_files(self, repo: str, number: int) -> list[dict[str, Any]]:
        self.pull(repo, number)
        return self.pull_patches[number]

    def open_pull_request(self, repo: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._check(repo)
        with self._lock:
            number = self._next_pr
            self._next_pr += 1
        url = f"https://github.example/{repo}/pull/{number}"
        commit_sha = sha256_hex(str(payload["files"]))[:40]
        self.pulls[number] = {
            "number": number,
            "title": payload["title"],
            "body": payload["body"],
            "state": "open",
            "author": "countersign-bot",
            "url": url,
            "head_sha": commit_sha,
            "base_ref": payload["base_branch"],
            "head_ref": payload["head_branch"],
        }
        self.pull_patches[number] = [
            self._patch(f["path"], _FILES.get(f["path"], ""), f["content"])
            for f in payload["files"]
        ]
        return {"number": number, "url": url, "commit_sha": commit_sha}

    def post_review(self, repo, number, commit_sha, body, comments) -> dict[str, Any]:
        self._check(repo)
        self.reviews.append({"number": number, "body": body, "comments": comments})
        return {"url": f"{self.pulls[number]['url']}#pullrequestreview-{len(self.reviews)}"}


class ScriptedLLM:
    """Stands in for Claude. First turn explores the repo, second turn submits."""

    def __init__(self, delay: float = 0.0):
        self._delay = delay

    def turn(self, *, agent, system, messages, tools, effort) -> Turn:
        if self._delay:
            time.sleep(self._delay)
        prompt = messages[0]["content"]
        explored = len(messages) > 1
        calls = (
            [ToolCall("submit-1", "submit", self._submission(agent, prompt))]
            if explored
            else self._explore(agent, prompt)
        )
        return Turn(
            assistant_content=[],
            tool_calls=calls,
            text="",
            stop_reason="tool_use",
            model="scripted-test",
            request_id=None,
            input_tokens=0,
            output_tokens=0,
        )

    @staticmethod
    def _explore(agent: str, prompt: str) -> list[ToolCall]:
        paths = {
            "planner": ["README.md", "app/main.py"],
            "coder": ["app/main.py", "app/auth.py"],
            "tester": ["tests/test_auth.py", "app/rate_limit.py"],
            "reviewer": ["app/auth.py"],
        }[agent]
        return [ToolCall("list-1", "list_files", {"prefix": ""})] + [
            ToolCall(f"read-{i}", "read_file", {"path": p}) for i, p in enumerate(paths)
        ]

    def _submission(self, agent: str, prompt: str) -> dict[str, Any]:
        return getattr(self, f"_{agent}")(prompt)

    @staticmethod
    def _planner(prompt: str) -> dict[str, Any]:
        match = re.search(r"<title>(.*?)</title>", prompt, re.DOTALL)
        title = match.group(1).strip() if match else "the requirement"
        return {
            "summary": f"Delivers \"{title}\" in two small pull requests: a reusable limiter "
            "first, then wiring it into the login route.",
            "tasks": [
                {
                    "title": "Add a sliding-window rate limiter",
                    "description": "Create an in-process limiter keyed by string, safe to call "
                    "from concurrent requests.",
                    "acceptance_criteria": [
                        "A key is refused after `limit` hits inside the window",
                        "Different keys do not affect one another",
                        "Hits older than the window stop counting",
                    ],
                    "files_likely_touched": ["app/rate_limit.py"],
                },
                {
                    "title": "Limit login attempts",
                    "description": "Use the limiter in POST /login and return 429 once a "
                    "username exceeds five attempts a minute.",
                    "acceptance_criteria": [
                        "The sixth attempt within a minute returns 429",
                        "Successful logins behave as before",
                    ],
                    "files_likely_touched": ["app/main.py"],
                },
            ],
            "open_questions": [
                "Should the limit apply per username, per IP address, or both?",
                "Limiter state is per process. Is that acceptable with several replicas?",
            ],
        }

    @staticmethod
    def _coder(prompt: str) -> dict[str, Any]:
        revised = "<feedback>" in prompt
        note = " Revised after reviewer feedback." if revised else ""
        if "Limit login attempts" in prompt:
            return {
                "summary": f"Guard POST /login with the rate limiter.{note}",
                "rationale": "Checking the limit before the password means a locked-out "
                "attacker learns nothing from further guesses.",
                "commit_message": "Limit login attempts per username",
                "files": [{"path": "app/main.py", "action": "update",
                           "content": _LOGIN_PATCHED}],
            }
        return {
            "summary": f"Add a thread-safe sliding-window RateLimiter.{note}",
            "rationale": "A deque per key keeps each check cheap, and the standard library is "
            "enough, so no new dependency is needed.",
            "commit_message": "Add sliding-window rate limiter",
            "files": [{"path": "app/rate_limit.py", "action": "create", "content": _LIMITER}],
        }

    @staticmethod
    def _tester(prompt: str) -> dict[str, Any]:
        return {
            "summary": "Unit tests for the limit, key isolation and window expiry.",
            "rationale": "These map one-to-one onto the acceptance criteria.",
            "coverage_notes": ["Concurrent access is not exercised."],
            "files": [{"path": "tests/test_rate_limit.py", "action": "create",
                       "content": _LIMITER_TESTS}],
        }

    @staticmethod
    def _reviewer(prompt: str) -> dict[str, Any]:
        match = re.search(r"<file path=\"(.*?)\"", prompt)
        path = match.group(1) if match else "app/auth.py"
        return {
            "summary": "The change does what it describes. One thing worth a second look.",
            "verdict": "needs_discussion",
            "comments": [{
                "path": path,
                "line": 1,
                "severity": "suggestion",
                "body": "Worth confirming behaviour here for unusually long input, since this "
                "runs before authentication.",
            }],
        }
