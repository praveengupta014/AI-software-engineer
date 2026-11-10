"""Server-side secrets: the Anthropic key, the GitHub token and the audit HMAC key.

They live in a 0600 JSON file beside the database, never in the database itself, and are
never sent to the browser. Environment variables win over the file, so a deployment can use
its own secret manager instead.
"""

import json
import os
import secrets
import threading
from typing import Any

from .config import get_settings

_lock = threading.Lock()
_FILE = "secrets.json"


def _path():
    return get_settings().data_dir / _FILE


def _load() -> dict[str, Any]:
    path = _path()
    return json.loads(path.read_text()) if path.exists() else {}


def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def update(**values: str) -> None:
    with _lock:
        data = _load()
        data.update(values)
        _save(data)


def anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or _load().get("anthropic_api_key", "")


def github_token() -> str:
    return os.environ.get("COUNTERSIGN_GITHUB_TOKEN") or _load().get("github_token", "")


def github_app() -> tuple[str, str] | None:
    """(app_id, private_key) if a GitHub App is connected. It takes priority over a token."""
    data = _load()
    app_id = os.environ.get("COUNTERSIGN_GITHUB_APP_ID") or data.get("github_app_id", "")
    key = os.environ.get("COUNTERSIGN_GITHUB_APP_PRIVATE_KEY") or data.get(
        "github_app_private_key", ""
    )
    return (app_id, key) if app_id and key else None


def github_webhook_secret() -> str:
    return os.environ.get("COUNTERSIGN_GITHUB_WEBHOOK_SECRET") or _load().get(
        "github_webhook_secret", ""
    )


def _stored(env: str, key: str) -> str:
    return os.environ.get(env) or _load().get(key, "")


def slack_webhook_url() -> str:
    return _stored("COUNTERSIGN_SLACK_WEBHOOK_URL", "slack_webhook_url")


def teams_webhook_url() -> str:
    return _stored("COUNTERSIGN_TEAMS_WEBHOOK_URL", "teams_webhook_url")


def public_url() -> str:
    return _stored("COUNTERSIGN_PUBLIC_URL", "public_url")


def jira_webhook_secret() -> str:
    return _stored("COUNTERSIGN_JIRA_WEBHOOK_SECRET", "jira_webhook_secret")


def linear_webhook_secret() -> str:
    return _stored("COUNTERSIGN_LINEAR_WEBHOOK_SECRET", "linear_webhook_secret")


def version() -> float:
    """Changes when stored credentials change, so other processes can pick them up."""
    path = _path()
    return path.stat().st_mtime if path.exists() else 0.0


def audit_key() -> bytes:
    """Created once and then fixed: changing it would invalidate every past audit event."""
    env = os.environ.get("COUNTERSIGN_AUDIT_KEY")
    if env:
        return env.encode()
    with _lock:
        data = _load()
        if "audit_key" not in data:
            data["audit_key"] = secrets.token_hex(32)
            _save(data)
        return data["audit_key"].encode()
