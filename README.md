# Countersign

AI agents that work like a software team, with a person signing off on every step.

You describe a requirement. Agents break it into tasks, write the code, write the tests, open a pull request and review it. Each of those stops at a human approval, and everything that happens is written to a tamper-evident audit trail.

```
requirement → plan → code → tests → pull request → review
               ▲      ▲       ▲          ▲           ▲
               └──────┴── human approval ┴───────────┘
```

## Quick start on one machine

You need a [Claude API key](https://console.anthropic.com/settings/keys) and a [fine-grained GitHub token](https://github.com/settings/personal-access-tokens/new) with read and write access to **Contents** and **Pull requests**. Agent usage is billed to your Anthropic account.

```bash
cd backend && uv sync && uv run uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev   # in a second terminal, then open http://localhost:5173
```

This uses SQLite in `backend/data` and runs agents inside the API process. Upgrades migrate the database automatically, but back up the folder first.

## Team deployment

This runs PostgreSQL, the API, separate agent workers and nginx.

```bash
./setup.sh                        # creates .env with strong random secrets
docker compose up --build -d      # then open http://localhost:8080
```

- **More capacity:** `docker compose up -d --scale worker=3`
- **Exposure:** the stack binds to localhost. Finish setup first, because the first visitor creates the owner account, then put TLS in front of it.
- **Backups:** `docker compose exec postgres pg_dump -U countersign countersign > backup.sql`. Also keep `.env` and the `countersign-data` volume, which hold the audit key and credentials.
- **More than one host:** workers share credentials through the `countersign-data` volume. Across hosts, set them with environment variables instead (see `.env.example`).

To bring an existing SQLite install across, with its audit chain intact, stop the old backend and run:

```bash
docker compose run --rm -v "$PWD/backend/data:/import:ro" backend \
  /srv/.venv/bin/python -m app.copy_to_postgres /import
```

The target database must be empty, so run this before finishing setup in the new stack.

### Connect a GitHub App

A GitHub App is the right choice for a team: access is per repository, tokens last an hour, and commits appear under the app's name.

1. [Create an app](https://github.com/settings/apps/new). Under **Repository permissions**, give **Contents** and **Pull requests** read and write, and **Issues** and **Metadata** read.
2. For webhooks, set the URL shown in **Settings**, choose a secret, and subscribe to **Pull requests** and **Issues**. The URL must be reachable from the internet. Leave webhooks off if it is not.
3. Generate a private key and copy the App ID.
4. Enter them in **Settings**, then use **Choose repositories** to install the app.

### Automatic drafts

With webhooks connected:

- **A new pull request** from an owner, member or collaborator gets a draft review. Drafts and PRs from outside the repository are skipped, so strangers cannot spend your tokens.
- **An issue labelled `countersign`** becomes a requirement and goes to the planner.

Both only start agents. The results wait for a person, and Countersign posts nothing to GitHub until then. New commits on an open PR do not trigger another review yet.

### Slack and Teams

In **Settings**, add an [incoming webhook for Slack](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/) or a Teams Workflows webhook, plus the address teammates use to open Countersign. Each proposal then posts a summary and a review link. Decisions still happen in Countersign. Messages are queued with the proposal and retried, so an outage cannot lose one or delay an agent.

### Jira and Linear

Add the webhook addresses and secrets shown in **Settings**, then link each Jira project or Linear team to a repository. A ticket labelled `countersign` becomes a requirement. The link decides the repository, so ticket text cannot choose where agents work. Unlinked projects are ignored.

## Repository memory

Notes left when rejecting or sending back work are kept per repository and agent, and added to later runs as team guidance. **Memory** lets you add conventions for every agent and turn any entry off. Only people write memory, never agents, so a prompt injection cannot plant lasting instructions. Each run records which memories it used.

## Insights

**Insights** shows approval rate, work approved without edits, time to decide, and estimated cost per pull request and agent. Costs come from token counts and the `COUNTERSIGN_PRICE_*` settings, and do not include cache writes, so your Anthropic invoice is the source of truth.

## Audit evidence

**Audit trail → Download pack** builds a signed ZIP for a date range: decisions, GitHub writes, access history, raw audit events, chain verification, and automatic checks that list any exceptions. It includes suggested SOC 2 control references to discuss with your auditor. It supports an audit, but it does not certify you.

## Measuring agents

`backend/evals` runs the agents against 16 fixed tasks with deterministic checks, including planted bugs, clean changes that must not be flagged, and prompt injections.

```bash
cd backend
uv run python -m evals.run                                  # shows the plan, spends nothing
uv run python -m evals.run --run                            # bills your Anthropic account
uv run python -m evals.run --run --baseline evals/baseline.json
```

Copy a good file from `evals/results` to `evals/baseline.json`. Later runs exit with an error if a case that passed there now fails, so this can gate prompt changes in CI.

## How agents run reliably

Agent work is a queue stored in the database. A run commits in the same transaction as the change that requested it, so it cannot be lost between the two.

- **A worker crashes:** its lease expires and another worker takes the run. Agents only read and propose, so running one again is safe.
- **A stalled worker wakes up late:** its attempt number is out of date, so its results are discarded.
- **Temporary failures** such as rate limits retry with backoff, up to three attempts. Permanent ones stop with an explanation.
- **A deploy stops a worker:** it returns its runs to the queue without using up an attempt.
- **Restarting the API** does not affect running agents.

### Forgotten password

Stop the backend, then run this from the `backend` folder and follow the prompts:

```bash
uv run python -m app.reset_password
```

Add `--generate` to have a password created and printed instead of typing one at the hidden prompt.

With Docker, use `docker compose run --rm -it backend /srv/.venv/bin/python -m app.reset_password`. The reset signs that account out everywhere and is recorded in the audit trail.

## How the approval gate works

- **Agents cannot change anything.** Each one gets `list_files`, `read_file` and a `submit` tool. A submission only creates a pending proposal.
- **There is one door to GitHub.** `pipeline._execute_external` is the only code that calls GitHub's write methods, and it refuses any proposal that is not approved.
- **Approval covers exact content.** The browser sends back the SHA-256 of the proposal the person was looking at. If the content has changed since, the approval fails with a 409.
- **People can edit first.** Edits make a new revision with a new hash, and the old and new hashes are recorded.
- **Risky changes need a tick.** Code, not the model, flags CI changes, likely secrets, dependency changes, infrastructure changes, deletions and large diffs. High-risk flags must be acknowledged before approval.
- **The AI never formally approves a PR.** Reviews post as plain comments, so merging stays with your normal branch rules.

Repository contents and PR text are treated as untrusted. A prompt injection can make an agent propose something bad, but it still has to get past a person, and it has no tool that acts directly.

## The audit trail

Every requirement, model turn, tool call, proposal, edit, decision and GitHub write becomes an event, committed in the same transaction as the state change it describes. Writes are serialised across every API and worker process, so the chain stays linear.

- Each event holds an HMAC over its content and the previous event's hash, so altering, removing or reordering a past event breaks the chain from there on.
- Database triggers reject `UPDATE` and `DELETE` on the table.
- The HMAC key is kept in `secrets.json`, not the database, so someone holding only the database file cannot re-sign it. For stronger separation, set `COUNTERSIGN_AUDIT_KEY` from a secret manager.
- **Verify chain** in the UI (`GET /api/audit/verify`) rechecks everything and names the first bad event.
- **Export** downloads the log as JSONL.

Prompts and file reads are stored as hashes to keep the log small. Proposal content is stored in full on the proposal.

The chain alone cannot detect deletion of the newest events. If that matters to you, copy the head hash from a verify run somewhere else on a schedule and compare.

## Known limits

- **Generated tests are not run.** The tester writes them and your CI runs them. The PR description says so.
- **A recovered run starts again from the beginning,** so its earlier tokens are spent again.
- **Accounts are name and password.** There is no SSO, and sign-in throttling is per API process.
- **Slack and Teams only notify.** Approving from inside a chat app is not supported.
- **Text files only.** Agents cannot read or change binary files.
- **Agents read the code at one commit.** A large repository costs more, because agents read files through the model.

## Layout

```
backend/app/
  pipeline.py        runs, decisions, the approval gate
  worker.py          job queue, leases and crash recovery
  webhooks.py        GitHub webhooks
  trackers.py        Jira and Linear webhooks
  notifications.py   Slack and Teams outbox
  memory.py          per-repository guidance
  insights.py        approval and cost measures
  compliance.py      signed evidence packs
  agents.py          prompts and the agent loop
  audit.py           hash chain and verification
  safety.py          path checks and risk flags
  github_client.py   GitHub token and App clients, and read-only RepoView
  llm.py             Claude wrapper
  vault.py           secrets file
  auth.py            accounts and sessions
  main.py            HTTP API
backend/evals/       fixed tasks for measuring agents
backend/migrations/  database schema history
backend/tests/       test suite, with a scripted model and in-memory GitHub
frontend/src/        React, Tailwind CSS, Motion
```

## Tests

```bash
cd backend && uv run pytest
```

Multi-process guarantees need PostgreSQL. Point the suite at an empty database to run everything there:

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/test uv run pytest
```
