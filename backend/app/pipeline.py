"""Orchestration: agent runs, human decisions, and execution of approved work.

The approval gate lives here. The rules:
  * Agents can only create pending proposals.
  * A human decision is checked against the hash of the exact payload the human saw.
  * _execute_external is the only caller of GitHub's write methods, and it refuses any
    proposal that is not in the approved state.
  * State changes commit in the same transaction as their audit event.
"""

import difflib
import json
import re
from typing import Any

import anthropic
import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, memory, notifications, vault
from .agents import AGENTS, AgentFailure, _check_plan, run_agent, tool_audit_data
from .audit import payload_hash
from .config import get_settings
from .db import read_session, write_tx
from .github_client import GitHub, GitHubAppClient, GitHubClient, GitHubError, RepoView
from .llm import LLM, AnthropicLLM, Turn
from .models import AgentRun, Proposal, Requirement, Task, iso_in, now_iso
from .safety import commentable_lines, has_high_risk, risk_flags
from .schemas import Plan, Review

KIND_AGENT = {"plan": "planner", "code": "coder", "tests": "tester", "review": "reviewer"}
KIND_LABEL = {
    "plan": "Plan", "code": "Code change", "tests": "Tests",
    "pull_request": "Pull request", "review": "PR review",
}


class PipelineError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Backends:
    def __init__(self) -> None:
        self.github: GitHub | None = None
        self.llm: LLM | None = None
        self._version: float | None = None

    def configure(self) -> None:
        """Build clients from the stored credentials."""
        settings = get_settings()
        anthropic_key, github_token = vault.anthropic_key(), vault.github_token()
        app = vault.github_app()
        if app:
            self.github = GitHubAppClient(app[0], app[1], settings.github_api_url)
        elif github_token:
            self.github = GitHubClient(github_token, settings.github_api_url)
        else:
            self.github = None
        self.llm = AnthropicLLM(anthropic_key, settings.model) if anthropic_key else None
        self._version = vault.version()

    def refresh(self) -> None:
        """Pick up credentials changed by another process."""
        if vault.version() != self._version:
            self.configure()

    def notify(self, run_id: str) -> None:
        """A run was queued. Workers poll, so this is only a hook for running inline in tests."""


backends = Backends()


# Agent runs ---------------------------------------------------------------------------


def create_run(
    s: Session,
    agent: str,
    *,
    repo: str,
    user: str,
    requirement_id: str | None = None,
    task_id: str | None = None,
    pr_number: int | None = None,
    feedback: str | None = None,
    actor_type: str = "human",
) -> AgentRun:
    run = AgentRun(
        agent=agent, repo=repo, requirement_id=requirement_id, task_id=task_id,
        pr_number=pr_number, feedback=feedback, started_by=user,
    )
    s.add(run)
    s.flush()
    audit.record(
        s, actor_type=actor_type, actor=user, action="run.requested", subject_type="run",
        subject_id=run.id, requirement_id=requirement_id,
        data={"agent": agent, "repo": repo, "task_id": task_id, "pr_number": pr_number,
              "with_feedback": bool(feedback)},
    )
    return run


def _emit(run: AgentRun, action: str, data: dict[str, Any]) -> None:
    with write_tx() as s:
        audit.record(
            s, actor_type="agent", actor=run.agent, action=action, subject_type="run",
            subject_id=run.id, requirement_id=run.requirement_id, data=data,
        )


class LeaseLost(Exception):
    """This worker no longer owns the run, so its results must be discarded."""


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, anthropic.RateLimitError | anthropic.APIConnectionError
                  | anthropic.InternalServerError | httpx.HTTPError):
        return True
    return isinstance(exc, GitHubError) and (exc.status == 429 or exc.status >= 500)


def execute_run(run_id: str, attempt: int) -> None:
    """Runs on a worker thread. Holds no database lock while the model or GitHub is working."""
    with write_tx() as s:
        run = s.get(AgentRun, run_id)
        audit.record(
            s, actor_type="agent", actor=run.agent, action="run.started", subject_type="run",
            subject_id=run.id, requirement_id=run.requirement_id,
            data={"model": get_settings().model, "attempt": attempt},
        )
    try:
        _perform_run(run, attempt)
    except LeaseLost:
        return
    except (AgentFailure, GitHubError, anthropic.APIError, httpx.HTTPError) as exc:
        if _is_retryable(exc):
            _retry_or_fail(run_id, attempt, exc)
        else:
            fail_run(run_id, _explain(exc), attempt)
    except Exception as exc:  # a run must never be left stuck as running
        fail_run(run_id, f"Unexpected error: {type(exc).__name__}: {exc}", attempt)
        raise


def _owned(run: AgentRun, attempt: int | None) -> bool:
    return attempt is None or (run.status == "running" and run.attempts == attempt)


def _retry_or_fail(run_id: str, attempt: int, exc: Exception) -> None:
    settings = get_settings()
    if attempt >= settings.run_max_attempts:
        fail_run(run_id, _explain(exc), attempt)
        return
    delay = settings.retry_base_seconds * 2 ** (attempt - 1)
    with write_tx() as s:
        run = s.get(AgentRun, run_id)
        if not _owned(run, attempt):
            return
        run.status, run.locked_by, run.heartbeat_at = "queued", None, None
        run.available_at = iso_in(delay)
        audit.record(
            s, actor_type="system", actor="countersign", action="run.retrying",
            subject_type="run", subject_id=run.id, requirement_id=run.requirement_id,
            data={"attempt": attempt, "retry_in_seconds": delay, "reason": _explain(exc)},
        )


def _explain(exc: Exception) -> str:
    """Turn provider errors into something a person can act on."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "Anthropic rejected the API key. Update it in Settings."
    if isinstance(exc, anthropic.RateLimitError):
        return "Anthropic rate limit reached. Wait a minute and run this step again."
    if isinstance(exc, anthropic.BadRequestError) and "credit" in str(exc).lower():
        return "Your Anthropic account is out of credit. Add credit, then run this step again."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach Anthropic. Check the connection and run this step again."
    if isinstance(exc, GitHubError) and exc.status == 409 and "empty" in str(exc).lower():
        return (
            "This repository has no commits yet, so there is no code to read. "
            "Add a first commit (a README is enough), then run this step again."
        )
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic returned an error ({exc.status_code}): {exc.message}"
    if isinstance(exc, GitHubError) and exc.status == 401:
        return "GitHub rejected the token. Update it in Settings."
    if isinstance(exc, GitHubError) and exc.status in (403, 404):
        return f"{exc} Check that the repository exists and the token can access it."
    return str(exc)


def request_stop(run_id: str, user: str) -> None:
    with write_tx() as s:
        run = s.get(AgentRun, run_id)
        if run is None:
            raise PipelineError(404, "Run not found")
        if run.status not in ("queued", "running"):
            raise PipelineError(409, "This run has already finished")
        run.stop_requested_by = user
        audit.record(
            s, actor_type="human", actor=user, action="run.stop_requested", subject_type="run",
            subject_id=run.id, requirement_id=run.requirement_id,
        )
        waiting = run.status == "queued"
    if waiting:  # nothing is working on it, so nobody else would notice the request
        fail_run(run_id, f"Stopped by {user}")


def replan(requirement_id: str, user: str) -> None:
    with write_tx() as s:
        req = s.get(Requirement, requirement_id)
        if req is None:
            raise PipelineError(404, "Requirement not found")
        if req.status not in ("failed", "rejected"):
            raise PipelineError(409, "Only a failed or rejected plan can be redone")
        req.status = "planning"
        run_id = create_run(
            s, "planner", repo=req.repo, user=user, requirement_id=req.id
        ).id
    backends.notify(run_id)


def fail_run(run_id: str, error: str, attempt: int | None = None) -> None:
    with write_tx() as s:
        run = s.get(AgentRun, run_id)
        if not _owned(run, attempt):
            return
        run.status, run.error, run.finished_at = "failed", error, now_iso()
        run.locked_by = None
        if run.task_id:
            s.get(Task, run.task_id).state = "blocked"
        elif run.requirement_id:
            s.get(Requirement, run.requirement_id).status = "failed"
        audit.record(
            s, actor_type="system", actor="countersign", action="run.failed", subject_type="run",
            subject_id=run.id, requirement_id=run.requirement_id, data={"error": error},
        )


def _perform_run(run: AgentRun, attempt: int) -> None:
    gh = backends.github
    if gh is None or backends.llm is None:
        raise AgentFailure("Connect Claude and GitHub in Settings first")
    context = _build_context(gh, run)
    guidance = memory.for_agent(run.repo, run.agent)
    if guidance:
        _emit(run, "memory.applied", {"memory_ids": [m.id for m in guidance]})
    spec = AGENTS[run.agent]

    def on_turn(turn: Turn) -> None:
        with write_tx() as s:
            row = s.get(AgentRun, run.id)
            if not _owned(row, attempt):
                raise LeaseLost
            stopper = row.stop_requested_by
            row.model = turn.model
            row.turns += 1
            row.input_tokens += turn.input_tokens
            row.output_tokens += turn.output_tokens
            row.cache_read_tokens += turn.cache_read_tokens
            audit.record(
                s, actor_type="agent", actor=run.agent, action="llm.turn", subject_type="run",
                subject_id=run.id, requirement_id=run.requirement_id,
                data={"model": turn.model, "stop_reason": turn.stop_reason,
                      "request_id": turn.request_id, "input_tokens": turn.input_tokens,
                      "output_tokens": turn.output_tokens,
                      "cache_read_tokens": turn.cache_read_tokens,
                      "tools_called": [c.name for c in turn.tool_calls],
                      "system_prompt_sha256": audit.sha256_hex(spec.system)},
            )
        if stopper:
            raise AgentFailure(f"Stopped by {stopper}")

    def on_tool(name: str, tool_input: dict, result: str, is_error: bool) -> None:
        with read_session() as s:
            if not _owned(s.get(AgentRun, run.id), attempt):
                raise LeaseLost
        _emit(run, "tool.called", tool_audit_data(name, tool_input, result, is_error))

    output = run_agent(
        backends.llm, spec, context["prompt"] + memory.prompt_block(guidance), context["view"],
        max_turns=get_settings().max_agent_turns, on_turn=on_turn, on_tool=on_tool,
    )
    payload = {**output.model_dump(), **context["extra"]}
    view: RepoView = context["view"]
    if "files" in payload:
        for f in payload["files"]:
            f["original"] = view.read(f["path"]) if f["action"] != "create" else None

    with write_tx() as s:
        row = s.get(AgentRun, run.id)
        if not _owned(row, attempt):
            raise LeaseLost
        row.status, row.finished_at, row.locked_by = "done", now_iso(), None
        kind = next(k for k, a in KIND_AGENT.items() if a == row.agent)
        _create_proposal(s, kind=kind, title=context["title"], payload=payload, run=row)
        if row.task_id:
            s.get(Task, row.task_id).state = "awaiting_approval"
        audit.record(
            s, actor_type="agent", actor=row.agent, action="run.completed", subject_type="run",
            subject_id=row.id, requirement_id=row.requirement_id,
            data={"turns": row.turns, "input_tokens": row.input_tokens,
                  "output_tokens": row.output_tokens},
        )


def _build_context(gh: GitHub, run: AgentRun) -> dict[str, Any]:
    with read_session() as s:
        task = s.get(Task, run.task_id) if run.task_id else None
        req = s.get(Requirement, run.requirement_id) if run.requirement_id else None
        feedback = _feedback_block(run)

        if run.agent == "planner":
            sha = gh.branch_sha(run.repo, req.base_branch)
            return {
                "prompt": (
                    f"Plan this requirement for {run.repo}.\n\n<requirement>\n"
                    f"<title>{req.title}</title>\n<body>{req.body}</body>\n</requirement>"
                    f"{feedback}"
                ),
                "view": RepoView(gh, run.repo, sha),
                "title": f"Plan: {req.title}",
                "extra": {"base_sha": sha, "base_branch": req.base_branch},
            }

        if run.agent == "coder":
            sha = gh.branch_sha(run.repo, req.base_branch)
            return {
                "prompt": f"Implement this task in {run.repo}.\n\n{_task_block(req, task)}{feedback}",
                "view": RepoView(gh, run.repo, sha),
                "title": f"Code: {task.title}",
                "extra": {"base_sha": sha, "base_branch": req.base_branch},
            }

        if run.agent == "tester":
            code = _latest_executed(s, task.id, "code")
            payload = code.payload
            overlay = {
                f["path"]: None if f["action"] == "delete" else f["content"]
                for f in payload["files"]
            }
            changed = "\n".join(f"- {f['action']} {f['path']}" for f in payload["files"])
            return {
                "prompt": (
                    f"Write tests in {run.repo} for this approved change.\n\n"
                    f"{_task_block(req, task)}\n\n<change_summary>{payload['summary']}"
                    f"</change_summary>\n<changed_files>\n{changed}\n</changed_files>{feedback}"
                ),
                "view": RepoView(gh, run.repo, payload["base_sha"], overlay),
                "title": f"Tests: {task.title}",
                "extra": {"base_sha": payload["base_sha"], "base_branch": payload["base_branch"]},
            }

        # reviewer
        pr = gh.pull(run.repo, run.pr_number)
        files = gh.pull_files(run.repo, run.pr_number)
        diff = "\n\n".join(
            f"<file path=\"{f['path']}\" status=\"{f['status']}\">\n"
            f"{f['patch'] or '[GitHub omitted this diff; use read_file]'}\n</file>"
            for f in files
        )
        return {
            "prompt": (
                f"Review pull request #{pr['number']} in {run.repo}.\n\n<pr>\n"
                f"<title>{pr['title']}</title>\n<author>{pr['author']}</author>\n"
                f"<description>{pr['body']}</description>\n</pr>\n\n<diff>\n{diff}\n</diff>"
                f"{feedback}"
            ),
            "view": RepoView(gh, run.repo, pr["head_sha"]),
            "title": f"Review: #{pr['number']} {pr['title']}",
            "extra": {"pr_number": pr["number"], "pr_url": pr["url"], "pr_title": pr["title"],
                      "commit_sha": pr["head_sha"]},
        }


def _task_block(req: Requirement, task: Task) -> str:
    criteria = "\n".join(f"- {c}" for c in task.acceptance_criteria)
    return (
        f"<requirement>\n<title>{req.title}</title>\n<body>{req.body}</body>\n</requirement>\n\n"
        f"<task>\n<title>{task.title}</title>\n<description>{task.description}</description>\n"
        f"<acceptance_criteria>\n{criteria}\n</acceptance_criteria>\n</task>"
    )


def _feedback_block(run: AgentRun) -> str:
    if not run.feedback:
        return ""
    return (
        "\n\nA human reviewer sent your previous submission back. Address their feedback."
        f"\n\n<feedback>\n{run.feedback}\n</feedback>"
    )


def _latest_executed(s: Session, task_id: str, kind: str) -> Proposal:
    proposal = s.scalar(
        select(Proposal)
        .where(Proposal.task_id == task_id, Proposal.kind == kind, Proposal.status == "executed")
        .order_by(Proposal.created_at.desc())
        .limit(1)
    )
    if proposal is None:
        raise AgentFailure(f"No approved {kind} proposal for this task")
    return proposal


# Proposals ----------------------------------------------------------------------------


def _create_proposal(
    s: Session,
    *,
    kind: str,
    title: str,
    payload: dict[str, Any],
    run: AgentRun | None = None,
    repo: str | None = None,
    requirement_id: str | None = None,
    task_id: str | None = None,
    actor_type: str = "agent",
    actor: str | None = None,
) -> Proposal:
    proposal = Proposal(
        kind=kind,
        title=title[:300],
        repo=run.repo if run else repo,
        run_id=run.id if run else None,
        requirement_id=run.requirement_id if run else requirement_id,
        task_id=run.task_id if run else task_id,
        payload=payload,
        payload_hash=payload_hash(payload),
        risk_flags=risk_flags(payload["files"]) if "files" in payload else [],
    )
    s.add(proposal)
    s.flush()
    audit.record(
        s, actor_type=actor_type, actor=actor or run.agent, action="proposal.created",
        subject_type="proposal", subject_id=proposal.id, requirement_id=proposal.requirement_id,
        data={"kind": kind, "title": proposal.title, "payload_hash": proposal.payload_hash,
              "risk_flags": [f["code"] for f in proposal.risk_flags]},
    )
    notifications.enqueue(s, proposal)
    return proposal


def _get_pending(s: Session, proposal_id: str, expected_hash: str | None = None) -> Proposal:
    proposal = s.get(Proposal, proposal_id)
    if proposal is None:
        raise PipelineError(404, "Proposal not found")
    if proposal.status != "pending":
        raise PipelineError(409, f"Proposal is already {proposal.status}")
    if expected_hash is not None and proposal.payload_hash != expected_hash:
        raise PipelineError(409, "Proposal changed since you loaded it. Reload and review again.")
    return proposal


def _decide(s: Session, p: Proposal, status: str, user: str, note: str, action: str) -> None:
    p.status, p.decided_by, p.decided_at, p.decision_note = status, user, now_iso(), note or None
    audit.record(
        s, actor_type="human", actor=user, action=action, subject_type="proposal",
        subject_id=p.id, requirement_id=p.requirement_id,
        data={"kind": p.kind, "payload_hash": p.payload_hash, "note": note,
              "edited_by": p.edited_by, "risk_flags": [f["code"] for f in p.risk_flags]},
    )


def approve(
    proposal_id: str, user: str, expected_hash: str, acknowledged_risks: bool, note: str
) -> None:
    run_id = None
    with write_tx() as s:
        p = _get_pending(s, proposal_id, expected_hash)
        if has_high_risk(p.risk_flags) and not acknowledged_risks:
            raise PipelineError(422, "This proposal has high-risk flags you must acknowledge.")
        _decide(s, p, "approved", user, note, "proposal.approved")
        external = p.kind in ("pull_request", "review")
        if not external:
            run_id = _apply_internal(s, p, user)
    if external:
        _execute_external(proposal_id, user)
    elif run_id:
        backends.notify(run_id)


def _apply_internal(s: Session, p: Proposal, user: str) -> str | None:
    """Advance the workflow for proposals with no effect outside Countersign. Returns the id of a
    follow-on agent run, if one should start."""
    p.status = "executed"
    if p.kind == "plan":
        req = s.get(Requirement, p.requirement_id)
        req.status = "in_progress"
        for position, t in enumerate(p.payload["tasks"]):
            s.add(Task(
                requirement_id=req.id, position=position, title=t["title"],
                description=t["description"], acceptance_criteria=t["acceptance_criteria"],
            ))
        s.flush()
        audit.record(
            s, actor_type="system", actor="countersign", action="tasks.created",
            subject_type="requirement", subject_id=req.id, requirement_id=req.id,
            data={"count": len(p.payload["tasks"]), "from_proposal": p.id},
        )
        return None

    task = s.get(Task, p.task_id)
    if p.kind == "code":
        task.stage, task.state = "tests", "running"
        return create_run(
            s, "tester", repo=p.repo, user=user, requirement_id=p.requirement_id, task_id=task.id
        ).id
    if p.kind == "tests":
        task.stage = "pr"
        _build_pr_proposal(s, task)
    return None


def _build_pr_proposal(s: Session, task: Task) -> Proposal:
    """Assembled by code from the approved proposals, so nothing new from a model enters here."""
    req = s.get(Requirement, task.requirement_id)
    code, tests = _latest_executed(s, task.id, "code"), _latest_executed(s, task.id, "tests")
    files = {
        f["path"]: {k: f[k] for k in ("path", "action", "content")}
        for source in (code, tests)
        for f in source.payload["files"]
    }
    criteria = "\n".join(f"- [ ] {c}" for c in task.acceptance_criteria)
    notes = "\n".join(f"- {n}" for n in tests.payload.get("coverage_notes", [])) or "- None"
    body = (
        f"{code.payload['summary']}\n\n## Why\n{code.payload['rationale']}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n## Tests\n{tests.payload['summary']}\n\n"
        f"Coverage notes:\n{notes}\n\nGenerated tests were not run by Countersign. "
        f"Check CI before merging.\n\n---\n"
        f"Prepared by Countersign agents. Code approved by {code.decided_by} "
        f"(`{code.payload_hash[:12]}`), tests approved by {tests.decided_by} "
        f"(`{tests.payload_hash[:12]}`)."
    )
    slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-")[:40].strip("-")
    payload = {
        "title": task.title,
        "body": body,
        "commit_message": code.payload["commit_message"],
        "base_branch": code.payload["base_branch"],
        "base_sha": code.payload["base_sha"],
        "head_branch": f"countersign/{task.id}-{slug}",
        "files": list(files.values()),
    }
    task.state = "awaiting_approval"
    return _create_proposal(
        s, kind="pull_request", title=f"Open PR: {task.title}", payload=payload, repo=req.repo,
        requirement_id=req.id, task_id=task.id, actor_type="system", actor="countersign",
    )


def _execute_external(proposal_id: str, user: str) -> None:
    """The only place Countersign changes anything on GitHub."""
    with read_session() as s:
        p = s.get(Proposal, proposal_id)
    if p.status != "approved":
        raise PipelineError(409, "Only an approved proposal can be executed")

    backends.refresh()
    gh = backends.github
    try:
        if gh is None:
            raise GitHubError(409, "Connect GitHub in Settings first")
        if p.kind == "pull_request":
            result = gh.open_pull_request(p.repo, p.payload)
            action, url = "github.pr_opened", result["url"]
        else:
            result = _post_review(gh, p)
            action, url = "github.review_posted", result["url"]
    except (GitHubError, httpx.HTTPError) as exc:
        with write_tx() as s:
            row = s.get(Proposal, proposal_id)
            row.status, row.error = "failed", str(exc)
            if row.task_id:
                s.get(Task, row.task_id).state = "blocked"
            audit.record(
                s, actor_type="system", actor="countersign", action="github.write_failed",
                subject_type="proposal", subject_id=row.id,
                requirement_id=row.requirement_id, data={"error": str(exc)},
            )
        raise PipelineError(502, f"GitHub rejected the action: {exc}") from exc

    run_id = None
    with write_tx() as s:
        row = s.get(Proposal, proposal_id)
        row.status, row.external_url, row.error = "executed", url, None
        audit.record(
            s, actor_type="system", actor="countersign", action=action, subject_type="proposal",
            subject_id=row.id, requirement_id=row.requirement_id,
            data={**result, "approved_by": row.decided_by, "payload_hash": row.payload_hash},
        )
        task = s.get(Task, row.task_id) if row.task_id else None
        if task and row.kind == "pull_request":
            task.stage, task.state = "review", "running"
            task.pr_number, task.pr_url = result["number"], result["url"]
            run_id = create_run(
                s, "reviewer", repo=row.repo, user=user, requirement_id=row.requirement_id,
                task_id=task.id, pr_number=result["number"],
            ).id
        elif task:
            task.stage, task.state = "done", "done"
            _complete_requirement_if_finished(s, task.requirement_id)
    if run_id:
        backends.notify(run_id)


def _post_review(gh: GitHub, p: Proposal) -> dict[str, Any]:
    """GitHub rejects a whole review if one comment is off the diff, so comments that do not
    land on a changed line are folded into the review body rather than lost."""
    payload = p.payload
    number = payload["pr_number"]
    allowed = {
        f["path"]: commentable_lines(f["patch"]) for f in gh.pull_files(p.repo, number)
    }
    inline, folded = [], []
    for c in payload["comments"]:
        text = f"**{c['severity']}:** {c['body']}"
        if c["line"] in allowed.get(c["path"], set()):
            inline.append({**c, "body": text})
        else:
            folded.append(f"- `{c['path']}:{c['line']}` {text}")
    verdict = payload["verdict"].replace("_", " ")
    body = (
        f"**AI review, approved by {p.decided_by}. Verdict: {verdict}**\n\n{payload['summary']}"
    )
    if folded:
        body += "\n\n" + "\n".join(folded)
    result = gh.post_review(p.repo, number, payload["commit_sha"], body, inline)
    return {**result, "pr_number": number, "inline_comments": len(inline),
            "folded_comments": len(folded)}


def _complete_requirement_if_finished(s: Session, requirement_id: str) -> None:
    s.flush()
    tasks = s.scalars(select(Task).where(Task.requirement_id == requirement_id)).all()
    if tasks and all(t.stage == "done" for t in tasks):
        s.get(Requirement, requirement_id).status = "done"


def retry_execution(proposal_id: str, user: str) -> None:
    """Retry a failed GitHub write. The approved payload is unchanged, so no new decision."""
    with write_tx() as s:
        p = s.get(Proposal, proposal_id)
        if p is None:
            raise PipelineError(404, "Proposal not found")
        if p.status != "failed":
            raise PipelineError(409, "Only a failed proposal can be retried")
        p.status, p.error = "approved", None
        if p.task_id:
            s.get(Task, p.task_id).state = "running"
        audit.record(
            s, actor_type="human", actor=user, action="proposal.retried",
            subject_type="proposal", subject_id=p.id, requirement_id=p.requirement_id,
            data={"payload_hash": p.payload_hash},
        )
    _execute_external(proposal_id, user)


def reject(proposal_id: str, user: str, note: str) -> None:
    with write_tx() as s:
        p = _get_pending(s, proposal_id)
        _decide(s, p, "rejected", user, note, "proposal.rejected")
        memory.learn_from_decision(s, p, note, user)
        if p.task_id:
            s.get(Task, p.task_id).state = "blocked"
        elif p.kind == "plan":
            s.get(Requirement, p.requirement_id).status = "rejected"


def request_changes(proposal_id: str, user: str, note: str) -> None:
    with write_tx() as s:
        p = _get_pending(s, proposal_id)
        if p.kind not in KIND_AGENT:
            raise PipelineError(422, "A pull request proposal has no agent to revise it")
        _decide(s, p, "changes_requested", user, note, "proposal.changes_requested")
        memory.learn_from_decision(s, p, note, user)
        previous = {k: v for k, v in p.payload.items() if k != "files"}
        if "files" in p.payload:
            previous["files"] = [
                {k: f[k] for k in ("path", "action", "content")} for f in p.payload["files"]
            ]
        feedback = f"{note}\n\nYour previous submission:\n{json.dumps(previous, indent=1)}"
        origin = s.get(AgentRun, p.run_id)
        run = create_run(
            s, KIND_AGENT[p.kind], repo=p.repo, user=user, requirement_id=p.requirement_id,
            task_id=p.task_id, pr_number=origin.pr_number, feedback=feedback,
        )
        if p.task_id:
            s.get(Task, p.task_id).state = "running"
        run_id = run.id
    backends.notify(run_id)


def edit(proposal_id: str, user: str, expected_hash: str, changes: dict[str, Any]) -> None:
    with write_tx() as s:
        p = _get_pending(s, proposal_id, expected_hash)
        old_hash = p.payload_hash
        try:
            payload = _apply_edit(p, changes)
        except ValidationError as exc:
            raise PipelineError(422, f"Invalid edit: {exc}") from exc
        if payload == p.payload:
            raise PipelineError(422, "That edit changes nothing")
        p.payload = payload
        p.payload_hash = payload_hash(payload)
        p.revision += 1
        p.edited_by = user
        if "files" in payload:
            p.risk_flags = risk_flags(payload["files"])
        audit.record(
            s, actor_type="human", actor=user, action="proposal.edited",
            subject_type="proposal", subject_id=p.id, requirement_id=p.requirement_id,
            data={"old_hash": old_hash, "new_hash": p.payload_hash, "revision": p.revision,
                  "fields": sorted(changes)},
        )


def _apply_edit(p: Proposal, changes: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(p.payload))
    if p.kind == "plan":
        fields = {k: changes.get(k, payload[k]) for k in ("summary", "tasks", "open_questions")}
        plan = Plan.model_validate(fields)
        for task in plan.tasks:
            task.acceptance_criteria = [c for c in task.acceptance_criteria if c.strip()]
        problems = _check_plan(None, plan)
        if problems:
            raise PipelineError(422, "; ".join(problems))
        payload.update(plan.model_dump())
    elif p.kind == "review":
        fields = {k: changes.get(k, payload[k]) for k in ("summary", "verdict", "comments")}
        payload.update(Review.model_validate(fields).model_dump())
    elif p.kind == "pull_request":
        for key in ("title", "body", "commit_message"):
            value = changes.get(key, payload[key])
            if not isinstance(value, str) or not value.strip():
                raise PipelineError(422, f"{key} must not be empty")
            payload[key] = value
    else:
        new_content = {f["path"]: f["content"] for f in changes.get("files", [])}
        for f in payload["files"]:
            if f["path"] in new_content:
                if f["action"] == "delete":
                    raise PipelineError(422, f"{f['path']} is being deleted; it has no content")
                f["content"] = new_content.pop(f["path"])
        if new_content:
            raise PipelineError(422, f"Unknown files in edit: {sorted(new_content)}")
    return payload


def start_task(task_id: str, user: str) -> None:
    """Start or restart whatever the task's current stage needs."""
    run_id = None
    with write_tx() as s:
        task = s.get(Task, task_id)
        if task is None:
            raise PipelineError(404, "Task not found")
        if task.state not in ("idle", "blocked"):
            raise PipelineError(409, f"Task is {task.state}")
        req = s.get(Requirement, task.requirement_id)
        if task.stage == "pr":
            _build_pr_proposal(s, task)
        elif task.stage == "done":
            raise PipelineError(409, "Task is already done")
        else:
            agent = {"code": "coder", "tests": "tester", "review": "reviewer"}[task.stage]
            task.state = "running"
            run_id = create_run(
                s, agent, repo=req.repo, user=user, requirement_id=req.id, task_id=task.id,
                pr_number=task.pr_number,
            ).id
    if run_id:
        backends.notify(run_id)


def proposal_out(p: Proposal, *, full: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": p.id, "kind": p.kind, "kind_label": KIND_LABEL[p.kind], "title": p.title,
        "repo": p.repo, "status": p.status, "run_id": p.run_id,
        "requirement_id": p.requirement_id, "task_id": p.task_id,
        "payload_hash": p.payload_hash, "revision": p.revision, "edited_by": p.edited_by,
        "risk_flags": p.risk_flags, "decided_by": p.decided_by, "decided_at": p.decided_at,
        "decision_note": p.decision_note, "external_url": p.external_url, "error": p.error,
        "created_at": p.created_at, "summary": p.payload.get("summary") or p.payload.get("body"),
        "file_count": len(p.payload.get("files", [])),
    }
    if full:
        payload = json.loads(json.dumps(p.payload))
        for f in payload.get("files", []):
            f["diff"] = _unified_diff(f)
        out["payload"] = payload
    return out


def _unified_diff(f: dict[str, Any]) -> str:
    old = (f.get("original") or "").splitlines()
    new = [] if f["action"] == "delete" else f["content"].splitlines()
    return "\n".join(
        difflib.unified_diff(old, new, f"a/{f['path']}", f"b/{f['path']}", lineterm="", n=4)
    )


