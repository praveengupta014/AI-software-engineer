"""Measures for the Insights page: how often agent work is accepted, and what it costs.

Cost is an estimate from recorded token counts and the prices in settings. Cache writes are not
recorded separately, so a real invoice can run slightly higher.
"""

from collections import defaultdict
from datetime import datetime
from statistics import median
from typing import Any

from sqlalchemy import select

from .config import get_settings
from .db import read_session
from .models import AgentRun, Proposal, Requirement, Task, iso_in

APPROVED = ("approved", "executed", "failed")
SENT_BACK = ("changes_requested",)
REJECTED = ("rejected",)
_KIND_ORDER = ["plan", "code", "tests", "pull_request", "review"]
_AGENT_ORDER = ["planner", "coder", "tester", "reviewer"]


def run_cost(run: AgentRun) -> float:
    s = get_settings()
    return (
        run.input_tokens * s.price_input_per_mtok
        + run.output_tokens * s.price_output_per_mtok
        + run.cache_read_tokens * s.price_cache_read_per_mtok
    ) / 1_000_000


def _seconds_between(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _outcomes(proposals: list[Proposal]) -> dict[str, Any]:
    decided = [p for p in proposals if p.decided_at]
    approved = [p for p in decided if p.status in APPROVED]
    as_is = sum(p.edited_by is None for p in approved)
    sent_back = sum(p.status in SENT_BACK for p in decided)
    rejected = sum(p.status in REJECTED for p in decided)
    return {
        "decided": len(decided),
        "approved_as_is": as_is,
        "approved_after_edit": len(approved) - as_is,
        "sent_back": sent_back,
        "rejected": rejected,
    }


def build(days: int) -> dict[str, Any]:
    since = iso_in(-days * 86400)
    with read_session() as s:
        proposals = s.scalars(select(Proposal).where(Proposal.created_at >= since)).all()
        runs = s.scalars(select(AgentRun).where(AgentRun.created_at >= since)).all()
        task_ids = {r.task_id for r in runs if r.task_id}
        tasks = {
            t.id: t for t in s.scalars(select(Task).where(Task.id.in_(task_ids)))
        } if task_ids else {}
        requirements = {r.id: r.title for r in s.scalars(select(Requirement))}

    # A person only reviews AI work here: a pull request proposal is assembled by code.
    judged = [p for p in proposals if p.kind != "pull_request"]
    overall = _outcomes(judged)
    approved = overall["approved_as_is"] + overall["approved_after_edit"]
    waits = [
        _seconds_between(p.created_at, p.decided_at) for p in proposals if p.decided_at
    ]

    by_agent: dict[str, dict[str, float]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
    task_cost: dict[str, float] = defaultdict(float)
    for run in runs:
        cost = run_cost(run)
        by_agent[run.agent]["tokens"] += run.input_tokens + run.output_tokens
        by_agent[run.agent]["cost"] += cost
        if run.task_id:
            task_cost[run.task_id] += cost

    pull_requests = [
        {
            "pr_number": tasks[task_id].pr_number,
            "pr_url": tasks[task_id].pr_url,
            "title": tasks[task_id].title,
            "requirement": requirements.get(tasks[task_id].requirement_id, ""),
            "cost": round(cost, 4),
        }
        for task_id, cost in task_cost.items()
        if tasks.get(task_id) and tasks[task_id].pr_number
    ]
    pull_requests.sort(key=lambda row: row["cost"], reverse=True)

    total_cost = sum(run_cost(r) for r in runs)
    return {
        "days": days,
        "overview": {
            **overall,
            "approval_rate": approved / overall["decided"] if overall["decided"] else None,
            "as_is_rate": overall["approved_as_is"] / approved if approved else None,
            "median_decision_seconds": median(waits) if waits else None,
            "estimated_cost": round(total_cost, 4),
            "average_pr_cost": (
                round(sum(p["cost"] for p in pull_requests) / len(pull_requests), 4)
                if pull_requests else None
            ),
            "failed_runs": sum(r.status == "failed" for r in runs),
            "total_runs": len(runs),
        },
        "by_kind": [
            {"kind": kind, **_outcomes([p for p in proposals if p.kind == kind])}
            for kind in _KIND_ORDER
            if any(p.kind == kind for p in proposals)
        ],
        "by_agent": sorted(
            (
                {"agent": a, "tokens": int(by_agent[a]["tokens"]),
                 "cost": round(by_agent[a]["cost"], 4)}
                for a in _AGENT_ORDER if a in by_agent
            ),
            key=lambda row: row["cost"], reverse=True,
        ),
        "pull_requests": pull_requests[:15],
        "prices": {
            "input": get_settings().price_input_per_mtok,
            "output": get_settings().price_output_per_mtok,
            "cache_read": get_settings().price_cache_read_per_mtok,
        },
    }
