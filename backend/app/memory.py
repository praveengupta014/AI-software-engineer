"""What each repository has taught the team, so agents do not repeat a corrected mistake.

Everything here is written by people: conventions added by hand, and the notes reviewers
leave when they reject or send back work. Agent output is never stored, so a prompt injection
cannot plant instructions that persist into later runs.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .db import read_session
from .models import Proposal, RepoMemory

MAX_ENTRIES = 30
MAX_CHARS = 6000
KIND_AGENT = {"plan": "planner", "code": "coder", "tests": "tester", "review": "reviewer"}


def learn_from_decision(s: Session, proposal: Proposal, note: str, user: str) -> None:
    text = note.strip()
    agent = KIND_AGENT.get(proposal.kind)
    if not agent:
        return
    exists = s.scalar(
        select(RepoMemory.id).where(
            RepoMemory.repo == proposal.repo, RepoMemory.applies_to == agent,
            RepoMemory.text == text,
        )
    )
    if exists:
        return
    memory = RepoMemory(
        repo=proposal.repo, kind="lesson", applies_to=agent, text=text,
        source_proposal_id=proposal.id, created_by=user,
    )
    s.add(memory)
    s.flush()
    audit.record(
        s, actor_type="system", actor="countersign", action="memory.learned",
        subject_type="memory", subject_id=memory.id, requirement_id=proposal.requirement_id,
        data={"repo": proposal.repo, "applies_to": agent, "from_proposal": proposal.id},
    )


def for_agent(repo: str, agent: str) -> list[RepoMemory]:
    """Conventions first, then the newest lessons, within a fixed budget."""
    with read_session() as s:
        rows = s.scalars(
            select(RepoMemory)
            .where(RepoMemory.repo == repo, RepoMemory.active.is_(True))
            .order_by(RepoMemory.created_at.desc())
        ).all()
    relevant = [m for m in rows if m.kind == "convention" or m.applies_to == agent]
    relevant.sort(key=lambda m: m.kind != "convention")
    chosen, used = [], 0
    for memory in relevant[:MAX_ENTRIES]:
        if used + len(memory.text) > MAX_CHARS:
            break
        chosen.append(memory)
        used += len(memory.text)
    return chosen


def prompt_block(memories: list[RepoMemory]) -> str:
    if not memories:
        return ""
    lines = "\n".join(f"- {m.text}" for m in memories)
    return (
        "\n\nYour human reviewers have asked for the following on this repository. "
        f"Follow it unless the task says otherwise.\n\n<team_guidance>\n{lines}\n</team_guidance>"
    )
