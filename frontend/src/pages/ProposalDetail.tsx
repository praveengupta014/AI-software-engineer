import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Fingerprint, Pencil, RotateCcw, ShieldAlert, TriangleAlert, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ActorChip } from "../components/ActorChip";
import { FileDiff } from "../components/Diff";
import { KIND_ICON } from "../components/ProposalRow";
import { Stamp } from "../components/Stamp";
import { Badge, Button, Card, ErrorNote, Field, Loading, PageHeader, SectionTitle, StatusBadge, cx, inputClass } from "../components/ui";
import { get, post, type FileChange, type Payload, type Proposal } from "../lib/api";
import { actionLabel, clockTime, compactNumber, shortHash } from "../lib/format";

const SEVERITY = { blocker: "clay", warning: "gold", suggestion: "ocean" } as const;
const VERDICT: Record<string, string> = {
  looks_good: "Looks good",
  needs_changes: "Needs changes",
  needs_discussion: "Needs discussion",
};

function Prose({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section>
      <SectionTitle>{label}</SectionTitle>
      <div className="leading-relaxed whitespace-pre-wrap text-ink-2">{children}</div>
    </section>
  );
}

function PlanView({ payload }: { payload: Payload }) {
  return (
    <div className="space-y-7">
      <Prose label="Approach">{payload.summary}</Prose>
      <section>
        <SectionTitle>Tasks</SectionTitle>
        <ol className="space-y-3">
          {payload.tasks.map((t: Payload, i: number) => (
            <Card key={i} className="p-4">
              <div className="flex gap-3">
                <span className="font-serif text-xl leading-tight text-ink-3 tabular-nums">{i + 1}</span>
                <div className="min-w-0">
                  <h3 className="font-semibold">{t.title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-ink-2">{t.description}</p>
                  <ul className="mt-2.5 space-y-1 text-sm">
                    {t.acceptance_criteria.map((c: string) => (
                      <li key={c} className="flex gap-2 text-ink-2"><span className="text-moss">✓</span> {c}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </Card>
          ))}
        </ol>
      </section>
      {payload.open_questions.length > 0 && (
        <section className="rounded-xl bg-gold-soft/70 p-4">
          <h2 className="mb-1.5 text-sm font-semibold text-gold">Questions the planner could not settle</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
            {payload.open_questions.map((q: string) => <li key={q}>{q}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

function Files({ files }: { files: FileChange[] }) {
  return (
    <section>
      <SectionTitle aside={`${files.length} ${files.length === 1 ? "file" : "files"}`}>Changes</SectionTitle>
      <div className="space-y-4">{files.map((f) => <FileDiff key={f.path} file={f} />)}</div>
    </section>
  );
}

function ChangeView({ payload }: { payload: Payload }) {
  return (
    <div className="space-y-7">
      <Prose label="Summary">{payload.summary}</Prose>
      <Prose label="Why this way">{payload.rationale}</Prose>
      {payload.coverage_notes?.length > 0 && (
        <section className="rounded-xl bg-gold-soft/70 p-4">
          <h2 className="mb-1.5 text-sm font-semibold text-gold">Coverage notes</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
            {payload.coverage_notes.map((n: string) => <li key={n}>{n}</li>)}
          </ul>
        </section>
      )}
      <Files files={payload.files} />
    </div>
  );
}

function PullRequestView({ payload }: { payload: Payload }) {
  return (
    <div className="space-y-7">
      <Card className="p-4 font-mono text-[13px] leading-relaxed">
        <div><span className="text-ink-3">branch </span>{payload.head_branch}</div>
        <div><span className="text-ink-3">into&nbsp;&nbsp; </span>{payload.base_branch} @ {shortHash(payload.base_sha, 7)}</div>
        <div><span className="text-ink-3">commit </span>{payload.commit_message}</div>
      </Card>
      <Prose label="Pull request description">{payload.body}</Prose>
      <Files files={payload.files} />
    </div>
  );
}

function ReviewView({ payload }: { payload: Payload }) {
  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">PR #{payload.pr_number}</span>
        <span className="text-ink-2">{payload.pr_title}</span>
        <Badge tone={payload.verdict === "looks_good" ? "moss" : "gold"}>{VERDICT[payload.verdict]}</Badge>
      </div>
      <Prose label="Review summary">{payload.summary}</Prose>
      <section>
        <SectionTitle aside={`${payload.comments.length} comments`}>Comments</SectionTitle>
        {payload.comments.length === 0 ? <p className="text-sm text-ink-3">The reviewer has nothing to flag.</p> : (
          <div className="space-y-3">
            {payload.comments.map((c: Payload, i: number) => (
              <Card key={i} className="p-4">
                <div className="mb-1.5 flex items-center gap-2">
                  <Badge tone={SEVERITY[c.severity as keyof typeof SEVERITY]}>{c.severity}</Badge>
                  <code className="min-w-0 truncate font-mono text-xs text-ink-2">{c.path}:{c.line}</code>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{c.body}</p>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Editor({ proposal, onDone }: { proposal: Proposal; onDone: () => void }) {
  const [draft, setDraft] = useState<Payload>(() => structuredClone(proposal.payload));
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () => {
      const payload = proposal.kind === "code" || proposal.kind === "tests"
        ? { files: draft.files.filter((f: FileChange) => f.action !== "delete").map((f: FileChange) => ({ path: f.path, content: f.content })) }
        : draft;
      return post(`/proposals/${proposal.id}`, { expected_hash: proposal.payload_hash, payload }, "PUT");
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["proposal", proposal.id] });
      onDone();
    },
  });
  const patch = (changes: Payload) => setDraft({ ...draft, ...changes });
  const patchItem = (key: string, index: number, changes: Payload) =>
    patch({ [key]: draft[key].map((item: Payload, i: number) => (i === index ? { ...item, ...changes } : item)) });

  return (
    <div className="space-y-5">
      {proposal.kind === "plan" && (
        <>
          <Field label="Approach">
            <textarea rows={3} value={draft.summary} onChange={(e) => patch({ summary: e.target.value })} className={inputClass} />
          </Field>
          {draft.tasks.map((t: Payload, i: number) => (
            <Card key={i} className="space-y-3 p-4">
              <Field label={`Task ${i + 1}`}>
                <input value={t.title} onChange={(e) => patchItem("tasks", i, { title: e.target.value })} className={inputClass} />
              </Field>
              <Field label="Description">
                <textarea rows={2} value={t.description} onChange={(e) => patchItem("tasks", i, { description: e.target.value })} className={inputClass} />
              </Field>
              <Field label="Acceptance criteria" hint="One per line">
                <textarea
                  rows={3}
                  value={t.acceptance_criteria.join("\n")}
                  onChange={(e) => patchItem("tasks", i, { acceptance_criteria: e.target.value.split("\n") })}
                  className={inputClass}
                />
              </Field>
            </Card>
          ))}
        </>
      )}
      {(proposal.kind === "code" || proposal.kind === "tests") &&
        draft.files.filter((f: FileChange) => f.action !== "delete").map((f: FileChange) => (
          <Field key={f.path} label={f.path}>
            <textarea
              rows={Math.min(24, f.content.split("\n").length + 1)}
              spellCheck={false}
              value={f.content}
              onChange={(e) => patch({ files: draft.files.map((x: FileChange) => (x.path === f.path ? { ...x, content: e.target.value } : x)) })}
              className={cx(inputClass, "font-mono text-[12.5px] leading-relaxed")}
            />
          </Field>
        ))}
      {proposal.kind === "pull_request" && (
        <>
          <Field label="Title"><input value={draft.title} onChange={(e) => patch({ title: e.target.value })} className={inputClass} /></Field>
          <Field label="Commit message"><input value={draft.commit_message} onChange={(e) => patch({ commit_message: e.target.value })} className={inputClass} /></Field>
          <Field label="Description"><textarea rows={14} value={draft.body} onChange={(e) => patch({ body: e.target.value })} className={inputClass} /></Field>
        </>
      )}
      {proposal.kind === "review" && (
        <>
          <Field label="Verdict">
            <select value={draft.verdict} onChange={(e) => patch({ verdict: e.target.value })} className={inputClass}>
              {Object.entries(VERDICT).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field label="Summary"><textarea rows={3} value={draft.summary} onChange={(e) => patch({ summary: e.target.value })} className={inputClass} /></Field>
          {draft.comments.map((c: Payload, i: number) => (
            <div key={i} className="flex items-start gap-2">
              <div className="flex-1">
                <Field label={`${c.path}:${c.line}`}>
                  <textarea rows={3} value={c.body} onChange={(e) => patchItem("comments", i, { body: e.target.value })} className={inputClass} />
                </Field>
              </div>
              <button
                type="button"
                aria-label={`Remove comment on ${c.path}`}
                onClick={() => patch({ comments: draft.comments.filter((_: Payload, n: number) => n !== i) })}
                className="mt-7 rounded p-1.5 text-ink-3 hover:bg-clay-soft hover:text-clay"
              >
                <X className="size-4" />
              </button>
            </div>
          ))}
        </>
      )}
      <ErrorNote error={save.error} />
      <div className="flex gap-2">
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>Save edits</Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </div>
  );
}

function DecisionPanel({ proposal, editing }: { proposal: Proposal; editing: boolean }) {
  const [note, setNote] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const client = useQueryClient();
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["proposal", proposal.id] });
    client.invalidateQueries({ queryKey: ["overview"] });
  };
  const decide = useMutation({
    mutationFn: ({ action, body }: { action: string; body: Payload }) => post(`/proposals/${proposal.id}/${action}`, body),
    onSuccess: refresh,
    onError: refresh,
  });
  const highRisk = proposal.risk_flags.some((f) => f.level === "high");
  const needsNote = note.trim().length < 3;
  const pendingAction = decide.isPending ? decide.variables?.action : null;

  return (
    <Card className="p-4">
      <h2 className="font-serif text-xl font-medium">Your decision</h2>
      <p className="mt-0.5 mb-3.5 text-[13px] leading-snug text-ink-2">Nothing happens until you decide. Your name goes on the record.</p>

      {highRisk && (
        <label className="mb-3 flex items-start gap-2 rounded-lg bg-clay-soft p-2.5 text-[13px] text-clay">
          <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} className="mt-0.5 accent-[var(--color-clay)]" />
          I have checked the high-risk items above.
        </label>
      )}

      <textarea
        rows={3}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Note for the record. Required to reject or send back."
        aria-label="Decision note"
        className={inputClass}
      />
      <ErrorNote error={decide.error} />
      <div className="mt-3 space-y-2">
        <Button
          variant="approve"
          className="w-full"
          busy={pendingAction === "approve"}
          disabled={decide.isPending || editing || (highRisk && !acknowledged)}
          onClick={() => decide.mutate({ action: "approve", body: { expected_hash: proposal.payload_hash, acknowledged_risks: acknowledged, note } })}
        >
          {proposal.kind === "pull_request" ? "Approve and open PR" : proposal.kind === "review" ? "Approve and post review" : "Approve"}
        </Button>
        <div className="grid grid-cols-2 gap-2">
          {proposal.kind !== "pull_request" && (
            <Button
              busy={pendingAction === "request-changes"}
              disabled={needsNote || decide.isPending || editing}
              title={needsNote ? "Add a note so the agent knows what to change" : undefined}
              onClick={() => decide.mutate({ action: "request-changes", body: { note } })}
            >
              Send back
            </Button>
          )}
          <Button
            variant="danger"
            className={proposal.kind === "pull_request" ? "col-span-2" : ""}
            busy={pendingAction === "reject"}
            disabled={needsNote || decide.isPending || editing}
            title={needsNote ? "Add a note explaining why" : undefined}
            onClick={() => decide.mutate({ action: "reject", body: { note } })}
          >
            Reject
          </Button>
        </div>
      </div>
      {editing && <p className="mt-2 text-xs text-ink-3">Save or cancel your edits to decide.</p>}
    </Card>
  );
}

function Activity({ proposal }: { proposal: Proposal }) {
  return (
    <section>
      <SectionTitle aside={proposal.run ? `${proposal.run.turns} turns · ${compactNumber(proposal.run.input_tokens + proposal.run.output_tokens)} tokens` : undefined}>
        How this was made
      </SectionTitle>
      <ol className="relative space-y-3 border-l border-line-strong pl-4">
        {proposal.events.map((e) => (
          <li key={e.seq} className="relative text-[13px]">
            <span className={cx("absolute top-1.5 -left-[20.5px] size-2 rounded-full ring-2 ring-paper", e.actor_type === "human" ? "bg-moss" : e.actor_type === "agent" ? "bg-ocean" : "bg-ink-3")} />
            <div className="flex flex-wrap items-center gap-1.5">
              <ActorChip type={e.actor_type} name={e.actor} />
              <span className="font-mono text-[11px] text-ink-3">{clockTime(e.ts)}</span>
            </div>
            <div className="mt-0.5 text-ink-2">
              {actionLabel(e.action)}
              {e.action === "tool.called" && (
                <span className="font-mono text-xs"> {e.data.tool}{e.data.input?.path ? ` ${e.data.input.path}` : ""}{e.data.is_error ? " (error)" : ""}</span>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function ProposalDetail() {
  const { id } = useParams();
  const [editing, setEditing] = useState(false);
  const client = useQueryClient();
  const { data: p, error, isLoading } = useQuery({
    queryKey: ["proposal", id],
    queryFn: () => get<Proposal>(`/proposals/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 4000 : false),
  });
  const retry = useMutation({
    mutationFn: () => post(`/proposals/${id}/retry`),
    onSettled: () => client.invalidateQueries({ queryKey: ["proposal", id] }),
  });
  useEffect(() => setEditing(false), [id]);

  if (isLoading) return <Loading />;
  if (!p) return <ErrorNote error={error} />;

  const Icon = KIND_ICON[p.kind];
  const back = p.requirement_id ? `/requirements/${p.requirement_id}` : "/reviews";

  return (
    <div>
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-1.5">
            <Link to={back} className="hover:text-ink">{p.requirement_id ? "Requirement" : "PR reviews"}</Link> / <Icon className="size-3.5" /> {p.kind_label}
          </span>
        }
        title={p.title}
      >
        {p.status === "pending" && !editing && (
          <Button onClick={() => setEditing(true)}><Pencil className="size-4" /> Edit</Button>
        )}
      </PageHeader>

      <div className="mb-7 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-ink-2">
        <StatusBadge status={p.status} />
        <span className="font-mono">{p.repo}</span>
        <span className="flex items-center gap-1 font-mono" title={`SHA-256 ${p.payload_hash}`}>
          <Fingerprint className="size-3.5" /> {shortHash(p.payload_hash)}
        </span>
        {p.revision > 1 && <span>Revision {p.revision}, edited by {p.edited_by}</span>}
        {p.external_url && (
          <a href={p.external_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-ocean hover:underline">
            View on GitHub <ExternalLink className="size-3.5" />
          </a>
        )}
      </div>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0">
          {editing ? <Editor proposal={p} onDone={() => setEditing(false)} /> : (
            <>
              {p.kind === "plan" && <PlanView payload={p.payload} />}
              {(p.kind === "code" || p.kind === "tests") && <ChangeView payload={p.payload} />}
              {p.kind === "pull_request" && <PullRequestView payload={p.payload} />}
              {p.kind === "review" && <ReviewView payload={p.payload} />}
            </>
          )}
        </div>

        <aside className="space-y-6 lg:sticky lg:top-6">
          {p.risk_flags.length > 0 && (
            <section className="rounded-xl border border-clay/25 bg-clay-soft/50 p-4">
              <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-clay"><ShieldAlert className="size-4" /> Automatic risk checks</h2>
              <ul className="space-y-1.5 text-[13px] text-ink-2">
                {p.risk_flags.map((f) => (
                  <li key={f.code + f.message} className="flex gap-1.5">
                    <TriangleAlert className={cx("mt-0.5 size-3.5 shrink-0", f.level === "high" ? "text-clay" : "text-gold")} />
                    <span>{f.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {p.status === "pending" && <DecisionPanel proposal={p} editing={editing} />}

          {p.decided_by && p.decided_at && (
            <div className="space-y-2">
              <Stamp status={p.status} by={p.decided_by} at={p.decided_at} />
              {p.decision_note && <p className="text-sm text-ink-2 italic">“{p.decision_note}”</p>}
            </div>
          )}

          {p.status === "failed" && (
            <Card className="space-y-3 p-4">
              <p className="text-sm text-clay">{p.error}</p>
              <ErrorNote error={retry.error} />
              <Button className="w-full" busy={retry.isPending} onClick={() => retry.mutate()}>
                <RotateCcw className="size-4" /> Retry GitHub action
              </Button>
            </Card>
          )}

          <Activity proposal={p} />
        </aside>
      </div>
    </div>
  );
}
