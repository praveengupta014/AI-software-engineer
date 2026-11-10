"""Deterministic checks on agent output. These run in code, not in the model, so a
prompt-injected agent cannot talk its way past them."""

import re
from pathlib import PurePosixPath
from typing import Any

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]+(?<![/.])$")

_SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
_DEPENDENCY_FILES = {
    "requirements.txt", "pyproject.toml", "uv.lock", "poetry.lock", "package.json",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.mod", "go.sum", "cargo.toml",
    "cargo.lock", "gemfile", "gemfile.lock",
}
_LARGE_CHANGE_LINES = 500


def path_problem(path: str) -> str | None:
    """Return why a repository path is unacceptable, or None if it is fine."""
    if not path or path != path.strip():
        return "path is empty or has surrounding whitespace"
    if "\\" in path or "\0" in path or path.startswith("/"):
        return "path must be relative and use forward slashes"
    parts = PurePosixPath(path).parts
    if ".." in parts or "." in parts:
        return "path must not contain '.' or '..' segments"
    if parts[0] == ".git":
        return "path must not be inside .git"
    return None


def risk_flags(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        flags.append({"level": level, "code": code, "message": message})

    total_lines = 0
    for f in files:
        path, name = f["path"], PurePosixPath(f["path"]).name
        content = f.get("content") or ""
        total_lines += content.count("\n")
        if path.startswith(".github/workflows/"):
            add("high", "ci_change", f"{path} changes a CI workflow, which runs with repo secrets")
        if name.lower() in _DEPENDENCY_FILES:
            add("medium", "dependency_change", f"{path} changes project dependencies")
        if name == "Dockerfile" or path.startswith(("infra/", "terraform/", "k8s/")):
            add("medium", "infra_change", f"{path} changes deployment infrastructure")
        if f["action"] == "delete":
            add("medium", "file_deleted", f"{path} would be deleted")
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                add("high", "possible_secret", f"{path} appears to contain a {label}")
    if total_lines > _LARGE_CHANGE_LINES:
        add("medium", "large_change", f"Large change: about {total_lines} lines")
    return flags


def has_high_risk(flags: list[dict[str, str]]) -> bool:
    return any(f["level"] == "high" for f in flags)


def commentable_lines(patch: str | None) -> set[int]:
    """New-file line numbers GitHub accepts inline comments on, from a unified diff."""
    lines: set[int] = set()
    if not patch:
        return lines
    current = 0
    for line in patch.splitlines():
        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if hunk:
            current = int(hunk.group(1))
        elif line.startswith(("-", "\\")):
            continue
        else:
            lines.add(current)
            current += 1
    return lines
