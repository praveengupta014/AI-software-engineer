import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, CircleAlert, ExternalLink, LoaderCircle, Play, RotateCcw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { LiveRun } from "../components/LiveRun";
import { ProposalRow } from "../components/ProposalRow";
import { Button, Card, EmptyState, ErrorNote, Loading, PageHeader, SectionTitle, StatusBadge, cx } from "../components/ui";
import { get, post, type ProposalSummary, type RequirementDetail as Data, type Task } from "../lib/api";
import { AGENT_LABEL } from "../lib/format";

const STAGES = [
  { key: "code", label: "Code" },
  { key: "tests", label: "Tests" },
  { key: "pr", label: "Pull request" },
  { key: "review", label: "Review" },
] as const;

function Stepper({ task }: { task: Task }) {
  const current = task.stage === "done" ? STAGES.length : STAGES.findIndex((s) => s.key === task.stage);
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {STAGES.map((stage, index) => {
        const finished = index < current;
        const active = index === current;
        return (
          <li key={stage.key} className="flex items-center gap-1">
            {index > 0 && <span className={cx("h-px w-5", finished || active ? "bg-moss" : "bg-line-strong")} />}
            <span
              className={cx(
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
                finished && "bg-moss-soft text-moss",
                active && task.state === "blocked" && "bg-clay-soft text-clay",
                active && task.state === "awaiting_approval" && "bg-gold-soft text-gold",
                active && (task.state === "running" || task.state === "idle") && "bg-ocean-soft text-ocean",
                !finished && !active && "text-ink-3",
              )}
            >
              {finished && <Check className="size-3.5" />}
              {active && task.state === "running" && <LoaderCircle className="size-3.5 animate-spin" />}
              {active && task.state === "blocked" && <CircleAlert className="size-3.5" />}
              {stage.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function TaskCard({ task, proposals, requirementId, index, failure }: {
  task: Task;
  proposals: ProposalSummary[];
  requirementId: string;
  index: number;
  failure?: string | null;
}) {
  const client = useQueryClient();
  const start = useMutation({
    mutationFn: () => post(`/tasks/${task.id}/start`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["requirement", requirementId] }),
  });
  const waiting = proposals.find((p) => p.status === "pending");
  const untouched = task.stage === "code" && task.state === "idle";

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-4">
        <span className="font-serif text-2xl leading-none text-ink-3 tabular-nums">{index + 1}</span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">{task.title}</h3>
          <p className="mt-1 text-sm leading-relaxed text-ink-2">{task.description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {waiting && (
            <Link to={`/proposals/${waiting.id}`} className="inline-flex items-center gap-1.5 rounded-lg bg-gold-soft px-3 py-2 text-sm font-semibold text-gold hover:bg-gold-soft/70">
              Review now <ArrowRight className="size-4" />
            </Link>
          )}
          {(task.state === "idle" || task.state === "blocked") && (
            <Button variant={untouched ? "primary" : "ghost"} busy={start.isPending} onClick={() => start.mutate()}>
              {untouched ? <Play className="size-4" /> : <RotateCcw className="size-4" />}
              {untouched ? "Start coding" : "Run this step again"}
            </Button>
          )}
          {task.pr_url && (
            <a href={task.pr_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-sm font-semibold text-ocean hover:underline">
              PR #{task.pr_number} <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-3.5">
        <Stepper task={task} />
        {task.stage === "done" && <StatusBadge status="done" />}
      </div>
      {task.state === "blocked" && failure && (
        <p className="mt-3 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">{failure}</p>
      )}
      <ErrorNote error={start.error} />
    </Card>
  );
}

function Replan({ id }: { id: string }) {
  const client = useQueryClient();
  const replan = useMutation({
    mutationFn: () => post(`/requirements/${id}/replan`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["requirement", id] }),
  });
  return (
    <>
      <Button variant="primary" busy={replan.isPending} onClick={() => replan.mutate()}>
        <RotateCcw className="size-4" /> Plan again
      </Button>
      <ErrorNote error={replan.error} />
    </>
  );
}

export default function RequirementDetail() {
  const { id } = useParams();
  const { data, error, isLoading } = useQuery({
    queryKey: ["requirement", id],
    queryFn: () => get<Data>(`/requirements/${id}`),
    refetchInterval: 1500,
  });
  if (isLoading) return <Loading />;
  if (!data) return <ErrorNote error={error} />;

  const plan = [...data.proposals].reverse().find((p) => p.kind === "plan");
  const planning = data.runs.find((r) => r.agent === "planner" && (r.status === "running" || r.status === "queued"));
  const active = data.runs.filter((r) => r.agent !== "planner" && (r.status === "running" || r.status === "queued"));
  const failedPlan = data.status === "failed" ? data.runs.findLast((r) => r.status === "failed") : null;
  const failureFor = (task: Task) => {
    const run = data.runs.findLast((r) => r.task_id === task.id);
    return run?.status === "failed" ? `${AGENT_LABEL[run.agent]} failed: ${run.error}` : null;
  };

  return (
    <div className="">
      <PageHeader
        eyebrow={<><Link to="/requirements" className="hover:text-ink">Requirements</Link> / <span className="font-mono">{data.repo}</span></>}
        title={data.title}
      >
        <StatusBadge status={data.status} />
      </PageHeader>

      <p className={`max-w-3xl leading-relaxed whitespace-pre-wrap text-ink-2 ${data.source_url ? "mb-2" : "mb-8"}`}>{data.body}</p>
      {data.source_url && (
        <a href={data.source_url} target="_blank" rel="noreferrer" className="mb-8 inline-flex items-center gap-1 text-sm font-semibold text-ocean hover:underline">
          From a GitHub issue <ExternalLink className="size-3.5" />
        </a>
      )}

      {failedPlan && <p className="mb-6 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">Planning failed: {failedPlan.error}</p>}

      {planning && (
        <section className="mb-8"><LiveRun run={planning} /></section>
      )}

      {active.length > 0 && (
        <section className="mb-8 space-y-3">{active.map((run) => <LiveRun key={run.id} run={run} />)}</section>
      )}

      {(data.status === "failed" || data.status === "rejected") && (
        <div className="mb-6"><Replan id={data.id} /></div>
      )}

      {plan && data.tasks.length === 0 && (
        <section className="mb-8">
          <SectionTitle>Plan</SectionTitle>
          <Card className="overflow-hidden"><ProposalRow proposal={plan} showStatus /></Card>
        </section>
      )}

      {data.tasks.length > 0 && (
        <section className="mb-9">
          <SectionTitle aside={`${data.tasks.filter((t) => t.stage === "done").length} of ${data.tasks.length} done`}>Tasks</SectionTitle>
          <div className="space-y-3">
            {data.tasks.map((task, index) => (
              <TaskCard
                key={task.id}
                task={task}
                index={index}
                requirementId={data.id}
                failure={failureFor(task)}
                proposals={data.proposals.filter((p) => p.task_id === task.id)}
              />
            ))}
          </div>
        </section>
      )}

      {data.proposals.length > 0 ? (
        <section>
          <SectionTitle>Everything proposed so far</SectionTitle>
          <Card className="divide-y divide-line overflow-hidden">
            {[...data.proposals].reverse().map((p) => <ProposalRow key={p.id} proposal={p} showStatus />)}
          </Card>
        </section>
      ) : !planning && !failedPlan && (
        <EmptyState icon={<LoaderCircle className="size-5" />} title="No proposals yet" />
      )}
    </div>
  );
}
