"""Shapes agents must submit, and request bodies for the API.

Agent models become strict tool schemas, so every field is required and they carry no
validation keywords (strict mode does not accept minLength and friends). Limits are
enforced in the agents' validators instead.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannedTask(AgentOutput):
    title: str
    description: str
    acceptance_criteria: list[str]
    files_likely_touched: list[str]


class Plan(AgentOutput):
    summary: str
    tasks: list[PlannedTask]
    open_questions: list[str]


class FileChange(AgentOutput):
    path: str
    action: Literal["create", "update", "delete"]
    content: str = Field(description="Complete new file content. Empty string for delete.")


class CodeChange(AgentOutput):
    summary: str
    rationale: str
    commit_message: str
    files: list[FileChange]


class TestChange(AgentOutput):
    summary: str
    rationale: str
    coverage_notes: list[str]
    files: list[FileChange]


class ReviewComment(AgentOutput):
    path: str
    line: int = Field(description="Line number in the new version of the file.")
    severity: Literal["blocker", "warning", "suggestion"]
    body: str


class Review(AgentOutput):
    summary: str
    verdict: Literal["looks_good", "needs_changes", "needs_discussion"]
    comments: list[ReviewComment]


class RequirementIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=20000)
    repo: str = Field(max_length=140)
    base_branch: str = Field(default="main", max_length=200)


class ReviewRequestIn(BaseModel):
    repo: str = Field(max_length=140)
    pr_number: int = Field(gt=0)


class ApproveIn(BaseModel):
    expected_hash: str
    acknowledged_risks: bool = False
    note: str = Field(default="", max_length=2000)


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=4000)


class EditIn(BaseModel):
    expected_hash: str
    payload: dict


class SetupIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=8, max_length=200)
    anthropic_key: str = Field(default="", max_length=500)
    github_token: str = Field(default="", max_length=500)


class LoginIn(BaseModel):
    name: str = Field(max_length=60)
    password: str = Field(max_length=200)


class CredentialsIn(BaseModel):
    anthropic_key: str = Field(default="", max_length=500)
    github_token: str = Field(default="", max_length=500)


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=8, max_length=200)


class GitHubAppIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=40)
    private_key: str = Field(min_length=100, max_length=10000)
    webhook_secret: str = Field(default="", max_length=500)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class MemoryIn(BaseModel):
    repo: str = Field(max_length=140)
    text: str = Field(min_length=3, max_length=1000)


class MemoryUpdateIn(BaseModel):
    active: bool | None = None
    text: str | None = Field(default=None, min_length=3, max_length=1000)


class NotificationsIn(BaseModel):
    public_url: str = Field(default="", max_length=300)
    slack_url: str = Field(default="", max_length=500)
    teams_url: str = Field(default="", max_length=800)


class NotificationTestIn(BaseModel):
    channel: Literal["slack", "teams"]


class TrackerSecretsIn(BaseModel):
    jira_secret: str = Field(default="", max_length=500)
    linear_secret: str = Field(default="", max_length=500)


class TrackerLinkIn(BaseModel):
    provider: Literal["jira", "linear"]
    project_key: str = Field(min_length=1, max_length=40)
    repo: str = Field(max_length=140)
    base_branch: str = Field(default="main", max_length=200)
