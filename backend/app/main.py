import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text

from . import (
    audit,
    auth,
    compliance,
    data_browser,
    insights,
    notifications,
    pipeline,
    trackers,
    vault,
    webhooks,
    worker,
)
from .auth import current_user
from .config import get_settings
from .db import init_db, read_session, write_tx
from .github_client import GitHub, GitHubError, check_app, check_token
from .llm import check_key
from .models import (
    AgentRun,
    AuditEvent,
    NotificationOutbox,
    Proposal,
    RepoMemory,
    Requirement,
    Task,
    TrackerLink,
    User,
    WorkerPresence,
    iso_in,
)
from .pipeline import PipelineError, backends, proposal_out
from .safety import BRANCH_RE, REPO_RE
from .schemas import (
    ApproveIn,
    CredentialsIn,
    EditIn,
    GitHubAppIn,
    LoginIn,
    MemoryIn,
    MemoryUpdateIn,
    NoteIn,
    NotificationsIn,
    NotificationTestIn,
    PasswordChangeIn,
    RequirementIn,
    ReviewRequestIn,
    SetupIn,
    TrackerLinkIn,
    TrackerSecretsIn,
    UserIn,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # On PostgreSQL a separate one-shot step migrates, so replicas never race to do it.
    init_db(settings.database_url, migrate=settings.is_sqlite)
    backends.configure()
    embedded = None
    if settings.embedded_worker:
        embedded = worker.Worker()
        thread = threading.Thread(target=embedded.run, name="worker", daemon=True)
        thread.start()
    yield
    if embedded:
        embedded.stop.set()
        thread.join(timeout=10)


app = FastAPI(title="Countersign", lifespan=lifespan)
api = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


@app.exception_handler(PipelineError)
def _pipeline_error(_request: Request, exc: PipelineError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.exception_handler(GitHubError)
def _github_error(_request: Request, exc: GitHubError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(httpx.HTTPError)
def _github_unreachable(_request: Request, _exc: httpx.HTTPError) -> JSONResponse:
    return JSONResponse({"detail": "Could not reach GitHub. Try again."}, status_code=502)


@app.get("/api/health")
def health() -> dict[str, Any]:
    with read_session() as s:
        s.execute(text("SELECT 1"))  # a load balancer should see a dead database as unhealthy
    return {
        "status": "ok",
        "configured": auth.has_users(),
        "needs": {
            "anthropic_key": not vault.anthropic_key(),
            "github_token": not (vault.github_token() or vault.github_app()),
        },
    }


@app.post("/api/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    webhooks.verify_signature(body, x_hub_signature_256)
    if not x_github_delivery:
        raise HTTPException(400, "Missing delivery id")
    return await run_in_threadpool(webhooks.handle, x_github_event, x_github_delivery, body)


@app.post("/api/webhooks/jira", status_code=202)
async def jira_webhook(
    request: Request,
    x_hub_signature: str | None = Header(default=None),
    x_atlassian_webhook_identifier: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    trackers.verify_jira(body, x_hub_signature)
    delivery = x_atlassian_webhook_identifier or audit.sha256_hex(body)
    ticket = trackers.parse_jira(json.loads(body))
    return await run_in_threadpool(trackers.handle, "jira", delivery, ticket)


@app.post("/api/webhooks/linear", status_code=202)
async def linear_webhook(
    request: Request,
    linear_signature: str | None = Header(default=None),
    linear_delivery: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    trackers.verify_linear(body, linear_signature)
    delivery = linear_delivery or audit.sha256_hex(body)
    ticket = trackers.parse_linear(json.loads(body))
    return await run_in_threadpool(trackers.handle, "linear", delivery, ticket)


def _validate_credentials(anthropic_key: str, github_token: str) -> str | None:
    """Check both against the real services. Returns the GitHub login."""
    settings = get_settings()
    if anthropic_key:
        problem = check_key(anthropic_key, settings.model)
        if problem:
            raise HTTPException(422, problem)
    login = None
    if github_token:
        login, problem = check_token(github_token, settings.github_api_url)
        if problem:
            raise HTTPException(422, problem)
    return login


def _store_credentials(anthropic_key: str, github_token: str) -> None:
    values = {}
    if anthropic_key:
        values["anthropic_api_key"] = anthropic_key
    if github_token:
        values["github_token"] = github_token
    if values:
        vault.update(**values)
        backends.configure()


@app.post("/api/setup", status_code=201)
def setup(body: SetupIn) -> dict[str, str]:
    """First run only: create the owner account and connect Claude and GitHub."""
    if auth.has_users():
        raise HTTPException(409, "Countersign is already set up")
    anthropic_key = body.anthropic_key.strip()
    github_token = body.github_token.strip()
    if not (anthropic_key or vault.anthropic_key()):
        raise HTTPException(422, "A Claude API key is required")
    if not (github_token or vault.github_token() or vault.github_app()):
        raise HTTPException(422, "A GitHub token is required")
    _validate_credentials(anthropic_key, github_token)
    name = body.name.strip()
    password_hash = auth.hash_password(body.password)
    with write_tx() as s:
        if s.scalar(select(func.count()).select_from(User)):
            raise HTTPException(409, "Countersign is already set up")
        s.add(User(name=name, password_hash=password_hash))
        audit.record(
            s, actor_type="human", actor=name, action="setup.completed", subject_type="system",
            subject_id="countersign",
        )
    _store_credentials(anthropic_key, github_token)
    return {"token": auth.create_session(name), "name": name}


@app.post("/api/auth/login")
def login(body: LoginIn) -> dict[str, str]:
    name = auth.verify_login(body.name, body.password)
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=name, action="auth.signed_in", subject_type="user",
            subject_id=name,
        )
    return {"token": auth.create_session(name), "name": name}


@app.post("/api/auth/logout")
def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> dict[str, bool]:
    if creds:
        auth.end_session(creds.credentials)
    return {"ok": True}


@api.post("/auth/change-password")
def change_password(
    body: PasswordChangeIn,
    user: str = Depends(current_user),
    creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> dict[str, bool]:
    auth.change_password(user, body.current_password, body.new_password, creds.credentials)
    return {"ok": True}


@api.delete("/users/{name}")
def remove_user(name: str, user: str = Depends(current_user)) -> dict[str, bool]:
    auth.remove_user(name, user)
    return {"ok": True}


@api.get("/me")
def me(user: str = Depends(current_user)) -> dict[str, str]:
    return {"name": user}


def _github() -> GitHub:
    backends.refresh()
    if backends.github is None:
        raise HTTPException(409, "Connect GitHub in Settings first")
    return backends.github


def _check_repo(repo: str) -> None:
    if not REPO_RE.match(repo):
        raise HTTPException(422, "Repository must look like owner/name")


@api.get("/github/repos")
def github_repos() -> list[dict[str, Any]]:
    return _github().repos()


@api.get("/github/repos/{owner}/{name}/branches")
def github_branches(owner: str, name: str) -> list[str]:
    _check_repo(f"{owner}/{name}")
    return _github().branches(f"{owner}/{name}")


@api.get("/github/repos/{owner}/{name}/pulls")
def github_pulls(owner: str, name: str) -> list[dict[str, Any]]:
    _check_repo(f"{owner}/{name}")
    return _github().open_pulls(f"{owner}/{name}")


def _data_table(table: str) -> data_browser.Table:
    if table not in data_browser.TABLES:
        raise HTTPException(404, "Unknown table")
    return data_browser.TABLES[table]


@api.get("/data")
def data_summary() -> dict[str, Any]:
    return data_browser.summary()


@api.get("/data/{table}")
def data_rows(
    table: str,
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    return data_browser.list_rows(_data_table(table), q.strip(), page)


@api.get("/data/{table}/{row_id}")
def data_row(table: str, row_id: str) -> dict[str, Any]:
    row = data_browser.get_row(_data_table(table), row_id)
    if row is None:
        raise HTTPException(404, "Row not found")
    return row


@api.get("/settings")
def settings_view() -> dict[str, Any]:
    settings = get_settings()
    anthropic_key, github_token = vault.anthropic_key(), vault.github_token()
    anthropic_problem = (
        check_key(anthropic_key, settings.model) if anthropic_key else "Not connected"
    )
    app_credentials = vault.github_app()
    app_details = None
    if app_credentials:
        app_details, github_problem = check_app(*app_credentials, settings.github_api_url)
        login_name = app_details["login"] if app_details else None
    elif github_token:
        login_name, github_problem = check_token(github_token, settings.github_api_url)
    else:
        login_name, github_problem = None, "Not connected"
    online_since = iso_in(-settings.lease_seconds)
    with read_session() as s:
        users = s.scalars(select(User).order_by(User.created_at)).all()
        workers = s.scalars(
            select(WorkerPresence).where(WorkerPresence.last_seen >= online_since)
        ).all()
        return {
            "model": settings.model,
            "anthropic": {"ok": anthropic_problem is None, "problem": anthropic_problem},
            "github": {
                "ok": github_problem is None, "problem": github_problem, "login": login_name,
                "mode": "app" if app_credentials else "token",
                "install_url": (
                    f"https://github.com/apps/{app_details['slug']}/installations/new"
                    if app_details else None
                ),
            },
            "webhooks": {
                "configured": bool(vault.github_webhook_secret()),
                "path": "/api/webhooks/github",
                "issue_label": webhooks.ISSUE_LABEL,
            },
            "workers": [{"id": w.id, "last_seen": w.last_seen} for w in workers],
            "notifications": {
                "slack": bool(vault.slack_webhook_url()),
                "teams": bool(vault.teams_webhook_url()),
                "public_url": vault.public_url(),
                "failed": s.scalar(
                    select(func.count()).select_from(NotificationOutbox)
                    .where(NotificationOutbox.status == "failed")
                ),
            },
            "trackers": {
                "jira_secret": bool(vault.jira_webhook_secret()),
                "linear_secret": bool(vault.linear_webhook_secret()),
                "label": trackers.LABEL,
                "links": [
                    {"id": t.id, "provider": t.provider, "project_key": t.project_key,
                     "repo": t.repo, "base_branch": t.base_branch}
                    for t in s.scalars(select(TrackerLink).order_by(TrackerLink.created_at))
                ],
            },
            "users": [{"name": u.name, "created_at": u.created_at} for u in users],
        }


@api.put("/settings/github-app")
def update_github_app(body: GitHubAppIn, user: str = Depends(current_user)) -> dict[str, bool]:
    app_id, private_key = body.app_id.strip(), body.private_key.strip()
    details, problem = check_app(app_id, private_key, get_settings().github_api_url)
    if problem:
        raise HTTPException(422, problem)
    vault.update(
        github_app_id=app_id,
        github_app_private_key=private_key,
        github_webhook_secret=body.webhook_secret.strip(),
    )
    backends.configure()
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="settings.github_app_connected",
            subject_type="system", subject_id="countersign",
            data={"app": details["slug"], "webhooks": bool(body.webhook_secret.strip())},
        )
    return {"ok": True}


@api.put("/settings/notifications")
def update_notifications(
    body: NotificationsIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    values: dict[str, str] = {}
    public_url = body.public_url.strip().rstrip("/")
    if public_url:
        if not public_url.startswith(("https://", "http://")):
            raise HTTPException(422, "The app address must start with https://")
        values["public_url"] = public_url
    for channel, url in (("slack", body.slack_url.strip()), ("teams", body.teams_url.strip())):
        if url:
            problem = notifications.url_problem(channel, url)
            if problem:
                raise HTTPException(422, problem)
            values[f"{channel}_webhook_url"] = url
    if not values:
        raise HTTPException(422, "Nothing to update")
    vault.update(**values)
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="settings.notifications_updated",
            subject_type="system", subject_id="countersign", data={"fields": sorted(values)},
        )
    return {"ok": True}


@api.post("/settings/notifications/test")
def test_notification(
    body: NotificationTestIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    url = notifications.channel_url(body.channel)
    if not url:
        raise HTTPException(409, f"Connect {body.channel.title()} first")
    try:
        notifications.send_test(body.channel, url)
    except notifications.PermanentFailure as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


@api.put("/settings/trackers")
def update_tracker_secrets(
    body: TrackerSecretsIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    values = {
        key: value for key, value in (
            ("jira_webhook_secret", body.jira_secret.strip()),
            ("linear_webhook_secret", body.linear_secret.strip()),
        ) if value
    }
    if not values:
        raise HTTPException(422, "Enter a secret to update")
    vault.update(**values)
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="settings.tracker_updated",
            subject_type="system", subject_id="countersign", data={"fields": sorted(values)},
        )
    return {"ok": True}


@api.post("/settings/tracker-links", status_code=201)
def add_tracker_link(body: TrackerLinkIn, user: str = Depends(current_user)) -> dict[str, bool]:
    _check_repo(body.repo)
    if not BRANCH_RE.match(body.base_branch):
        raise HTTPException(422, "Invalid branch name")
    project = body.project_key.strip().upper()
    with write_tx() as s:
        if s.scalar(select(TrackerLink).where(
            TrackerLink.provider == body.provider, TrackerLink.project_key == project
        )):
            raise HTTPException(409, "That project is already linked")
        link = TrackerLink(provider=body.provider, project_key=project, repo=body.repo,
                           base_branch=body.base_branch, created_by=user)
        s.add(link)
        s.flush()
        audit.record(
            s, actor_type="human", actor=user, action="settings.tracker_linked",
            subject_type="tracker_link", subject_id=link.id,
            data={"provider": body.provider, "project": project, "repo": body.repo},
        )
    return {"ok": True}


@api.delete("/settings/tracker-links/{link_id}")
def remove_tracker_link(link_id: str, user: str = Depends(current_user)) -> dict[str, bool]:
    with write_tx() as s:
        link = s.get(TrackerLink, link_id)
        if link is None:
            raise HTTPException(404, "Link not found")
        data = {"provider": link.provider, "project": link.project_key, "repo": link.repo}
        s.delete(link)
        audit.record(
            s, actor_type="human", actor=user, action="settings.tracker_unlinked",
            subject_type="tracker_link", subject_id=link_id, data=data,
        )
    return {"ok": True}


@api.get("/memory")
def list_memory(repo: str | None = None) -> dict[str, Any]:
    query = select(RepoMemory).order_by(RepoMemory.created_at.desc())
    if repo:
        query = query.where(RepoMemory.repo == repo)
    with read_session() as s:
        rows = s.scalars(query).all()
        repos = sorted(set(s.scalars(select(RepoMemory.repo))))
    columns = [c.name for c in RepoMemory.__table__.columns]
    return {"repos": repos, "items": [{c: getattr(m, c) for c in columns} for m in rows]}


@api.post("/memory", status_code=201)
def add_memory(body: MemoryIn, user: str = Depends(current_user)) -> dict[str, str]:
    _check_repo(body.repo)
    with write_tx() as s:
        item = RepoMemory(repo=body.repo, kind="convention", text=body.text.strip(),
                          created_by=user)
        s.add(item)
        s.flush()
        audit.record(
            s, actor_type="human", actor=user, action="memory.added", subject_type="memory",
            subject_id=item.id, data={"repo": body.repo, "text_sha256": audit.sha256_hex(item.text)},
        )
        return {"id": item.id}


@api.put("/memory/{memory_id}")
def update_memory(
    memory_id: str, body: MemoryUpdateIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    with write_tx() as s:
        item = s.get(RepoMemory, memory_id)
        if item is None:
            raise HTTPException(404, "Memory not found")
        if body.active is not None:
            item.active = body.active
        if body.text is not None:
            item.text = body.text.strip()
        audit.record(
            s, actor_type="human", actor=user, action="memory.updated", subject_type="memory",
            subject_id=item.id, data={"active": item.active, "repo": item.repo,
                                      "text_sha256": audit.sha256_hex(item.text)},
        )
    return {"ok": True}


@api.get("/insights")
def get_insights(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    return insights.build(days)


@api.get("/compliance/export")
def export_compliance(
    start: date, end: date, user: str = Depends(current_user)
) -> Response:
    if end < start:
        raise HTTPException(422, "The end date is before the start date")
    pack, result = compliance.build_pack(start.isoformat(), end.isoformat(), user)
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="compliance.exported",
            subject_type="audit", subject_id="evidence",
            data={"start": start.isoformat(), "end": end.isoformat(), **result},
        )
    name = f"countersign-evidence-{start}-to-{end}.zip"
    return Response(
        pack, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@api.put("/settings/credentials")
def update_credentials(body: CredentialsIn, user: str = Depends(current_user)) -> dict[str, bool]:
    anthropic_key, github_token = body.anthropic_key.strip(), body.github_token.strip()
    if not (anthropic_key or github_token):
        raise HTTPException(422, "Enter a key or token to update")
    _validate_credentials(anthropic_key, github_token)
    _store_credentials(anthropic_key, github_token)
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="settings.credentials_updated",
            subject_type="system", subject_id="countersign",
            data={"anthropic": bool(anthropic_key), "github": bool(github_token)},
        )
    return {"ok": True}


@api.post("/users", status_code=201)
def add_user(body: UserIn, user: str = Depends(current_user)) -> dict[str, bool]:
    name = body.name.strip()
    password_hash = auth.hash_password(body.password)
    with write_tx() as s:
        taken = s.scalar(select(User).where(func.lower(User.name) == name.lower()))
        if taken:
            raise HTTPException(409, "That name is already taken")
        s.add(User(name=name, password_hash=password_hash))
        audit.record(
            s, actor_type="human", actor=user, action="user.added", subject_type="user",
            subject_id=name,
        )
    return {"ok": True}


def _run_out(r: AgentRun) -> dict[str, Any]:
    hidden = {"feedback", "locked_by", "heartbeat_at", "available_at"}
    return {c.name: getattr(r, c.name) for c in AgentRun.__table__.columns if c.name not in hidden}


def _live_run_out(s, r: AgentRun) -> dict[str, Any]:
    """A run plus its most recent tool calls, so people can watch an agent work."""
    calls = s.scalars(
        select(AuditEvent)
        .where(AuditEvent.subject_id == r.id, AuditEvent.action == "tool.called")
        .order_by(AuditEvent.seq.desc())
        .limit(6)
    ).all()
    steps = [
        {"seq": e.seq, "tool": e.data.get("tool"), "is_error": e.data.get("is_error"),
         "path": (e.data.get("input") or {}).get("path")
         or (e.data.get("input") or {}).get("prefix")}
        for e in reversed(calls)
    ]
    return {**_run_out(r), "steps": steps}


def _task_out(t: Task) -> dict[str, Any]:
    return {c.name: getattr(t, c.name) for c in Task.__table__.columns}


def _req_out(r: Requirement) -> dict[str, Any]:
    return {c.name: getattr(r, c.name) for c in Requirement.__table__.columns}


@api.get("/overview")
def overview() -> dict[str, Any]:
    with read_session() as s:
        pending = s.scalars(
            select(Proposal).where(Proposal.status == "pending").order_by(Proposal.created_at)
        ).all()
        active = s.scalars(
            select(AgentRun)
            .where(AgentRun.status.in_(("queued", "running")))
            .order_by(AgentRun.created_at)
        ).all()
        recent = s.scalars(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(12)).all()
        decided = dict(s.execute(
            select(Proposal.status, func.count()).group_by(Proposal.status)
        ).all())
        tokens = s.execute(
            select(
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
            )
        ).one()
        return {
            "pending": [proposal_out(p, full=False) for p in pending],
            "active_runs": [_live_run_out(s, r) for r in active],
            "recent_events": [audit.event_dict(e) for e in recent],
            "stats": {
                "awaiting": decided.get("pending", 0),
                "executed": decided.get("executed", 0),
                "sent_back": decided.get("rejected", 0) + decided.get("changes_requested", 0),
                "failed": decided.get("failed", 0),
                "audit_events": s.scalar(select(func.count()).select_from(AuditEvent)),
                "input_tokens": tokens[0],
                "output_tokens": tokens[1],
            },
        }


@api.get("/requirements")
def list_requirements() -> list[dict[str, Any]]:
    with read_session() as s:
        reqs = s.scalars(select(Requirement).order_by(Requirement.created_at.desc())).all()
        out = []
        for r in reqs:
            tasks = s.scalars(select(Task).where(Task.requirement_id == r.id)).all()
            waiting = s.scalar(
                select(func.count()).select_from(Proposal).where(
                    Proposal.requirement_id == r.id, Proposal.status == "pending"
                )
            )
            out.append({
                **_req_out(r),
                "task_count": len(tasks),
                "tasks_done": sum(t.stage == "done" for t in tasks),
                "awaiting": waiting,
            })
        return out


@api.post("/requirements", status_code=201)
def create_requirement(body: RequirementIn, user: str = Depends(current_user)) -> dict[str, str]:
    if not REPO_RE.match(body.repo):
        raise HTTPException(422, "Repository must look like owner/name")
    if not BRANCH_RE.match(body.base_branch):
        raise HTTPException(422, "Invalid branch name")
    with write_tx() as s:
        req = Requirement(
            title=body.title, body=body.body, repo=body.repo,
            base_branch=body.base_branch, created_by=user,
        )
        s.add(req)
        s.flush()
        audit.record(
            s, actor_type="human", actor=user, action="requirement.created",
            subject_type="requirement", subject_id=req.id, requirement_id=req.id,
            data={"title": req.title, "repo": req.repo, "base_branch": req.base_branch,
                  "body_sha256": audit.sha256_hex(req.body)},
        )
        run = pipeline.create_run(
            s, "planner", repo=req.repo, user=user, requirement_id=req.id
        )
        req_id, run_id = req.id, run.id
    backends.notify(run_id)
    return {"id": req_id}


@api.get("/requirements/{requirement_id}")
def get_requirement(requirement_id: str) -> dict[str, Any]:
    with read_session() as s:
        req = s.get(Requirement, requirement_id)
        if req is None:
            raise HTTPException(404, "Requirement not found")
        tasks = s.scalars(
            select(Task).where(Task.requirement_id == req.id).order_by(Task.position)
        ).all()
        proposals = s.scalars(
            select(Proposal).where(Proposal.requirement_id == req.id)
            .order_by(Proposal.created_at)
        ).all()
        runs = s.scalars(
            select(AgentRun).where(AgentRun.requirement_id == req.id)
            .order_by(AgentRun.created_at)
        ).all()
        return {
            **_req_out(req),
            "tasks": [_task_out(t) for t in tasks],
            "proposals": [proposal_out(p, full=False) for p in proposals],
            "runs": [_live_run_out(s, r) for r in runs],
        }


@api.post("/requirements/{requirement_id}/replan", status_code=202)
def replan(requirement_id: str, user: str = Depends(current_user)) -> dict[str, bool]:
    pipeline.replan(requirement_id, user)
    return {"ok": True}


@api.post("/runs/{run_id}/stop", status_code=202)
def stop_run(run_id: str, user: str = Depends(current_user)) -> dict[str, bool]:
    pipeline.request_stop(run_id, user)
    return {"ok": True}


@api.post("/tasks/{task_id}/start", status_code=202)
def start_task(task_id: str, user: str = Depends(current_user)) -> dict[str, bool]:
    pipeline.start_task(task_id, user)
    return {"ok": True}


@api.get("/reviews")
def list_reviews() -> dict[str, Any]:
    with read_session() as s:
        proposals = s.scalars(
            select(Proposal).where(Proposal.kind == "review", Proposal.task_id.is_(None))
            .order_by(Proposal.created_at.desc())
        ).all()
        runs = s.scalars(
            select(AgentRun).where(AgentRun.agent == "reviewer", AgentRun.task_id.is_(None))
            .order_by(AgentRun.created_at.desc()).limit(50)
        ).all()
        return {
            "proposals": [proposal_out(p, full=False) for p in proposals],
            "runs": [_live_run_out(s, r) for r in runs],
        }


@api.post("/reviews", status_code=202)
def request_review(body: ReviewRequestIn, user: str = Depends(current_user)) -> dict[str, str]:
    if not REPO_RE.match(body.repo):
        raise HTTPException(422, "Repository must look like owner/name")
    with write_tx() as s:
        run = pipeline.create_run(
            s, "reviewer", repo=body.repo, user=user, pr_number=body.pr_number
        )
        run_id = run.id
    backends.notify(run_id)
    return {"run_id": run_id}


@api.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str) -> dict[str, Any]:
    with read_session() as s:
        p = s.get(Proposal, proposal_id)
        if p is None:
            raise HTTPException(404, "Proposal not found")
        ids = [i for i in (p.id, p.run_id) if i]
        events = s.scalars(
            select(AuditEvent).where(AuditEvent.subject_id.in_(ids)).order_by(AuditEvent.seq)
        ).all()
        run = s.get(AgentRun, p.run_id) if p.run_id else None
        return {
            **proposal_out(p),
            "run": _run_out(run) if run else None,
            "events": [audit.event_dict(e) for e in events],
        }


@api.put("/proposals/{proposal_id}")
def edit_proposal(
    proposal_id: str, body: EditIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    pipeline.edit(proposal_id, user, body.expected_hash, body.payload)
    return {"ok": True}


@api.post("/proposals/{proposal_id}/approve")
def approve_proposal(
    proposal_id: str, body: ApproveIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    pipeline.approve(proposal_id, user, body.expected_hash, body.acknowledged_risks, body.note)
    return {"ok": True}


@api.post("/proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: str, body: NoteIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    pipeline.reject(proposal_id, user, body.note)
    return {"ok": True}


@api.post("/proposals/{proposal_id}/request-changes")
def request_changes(
    proposal_id: str, body: NoteIn, user: str = Depends(current_user)
) -> dict[str, bool]:
    pipeline.request_changes(proposal_id, user, body.note)
    return {"ok": True}


@api.post("/proposals/{proposal_id}/retry")
def retry_proposal(proposal_id: str, user: str = Depends(current_user)) -> dict[str, bool]:
    pipeline.retry_execution(proposal_id, user)
    return {"ok": True}


def _audit_query(actor_type: str | None, action: str | None, subject_id: str | None):
    query = select(AuditEvent)
    if actor_type:
        query = query.where(AuditEvent.actor_type == actor_type)
    if action:
        query = query.where(AuditEvent.action.startswith(action, autoescape=True))
    if subject_id:
        query = query.where(
            (AuditEvent.subject_id == subject_id) | (AuditEvent.requirement_id == subject_id)
        )
    return query


@api.get("/audit")
def list_audit(
    actor_type: str | None = None,
    action: str | None = None,
    subject_id: str | None = None,
    before_seq: int | None = None,
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    query = _audit_query(actor_type, action, subject_id)
    if before_seq:
        query = query.where(AuditEvent.seq < before_seq)
    with read_session() as s:
        rows = s.scalars(query.order_by(AuditEvent.seq.desc()).limit(limit + 1)).all()
        page = rows[:limit]
        return {
            "events": [audit.event_dict(e) for e in page],
            "next_before_seq": page[-1].seq if len(rows) > limit else None,
        }


@api.get("/audit/verify")
def verify_audit(user: str = Depends(current_user)) -> dict[str, Any]:
    result = audit.verify_chain()
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="audit.verified", subject_type="audit",
            subject_id="chain", data={"ok": result["ok"], "checked": result["checked"],
                                      "first_bad_seq": result["first_bad_seq"]},
        )
    return result


@api.get("/audit/export")
def export_audit(user: str = Depends(current_user)) -> Response:
    with write_tx() as s:
        audit.record(
            s, actor_type="human", actor=user, action="audit.exported", subject_type="audit",
            subject_id="chain",
        )
    with read_session() as s:
        rows = s.scalars(select(AuditEvent).order_by(AuditEvent.seq)).all()
        body = "\n".join(json.dumps(audit.event_dict(e), ensure_ascii=False) for e in rows)
    return Response(
        body + "\n",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="countersign-audit.jsonl"'},
    )


app.include_router(api)
