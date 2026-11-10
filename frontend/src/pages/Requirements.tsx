import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FilePlus2, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Loading, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { RepoPicker } from "../components/RepoPicker";
import { get, post, type RequirementRow } from "../lib/api";
import { timeAgo } from "../lib/format";

function NewRequirement({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const client = useQueryClient();
  const navigate = useNavigate();

  const create = useMutation({
    mutationFn: () => post<{ id: string }>("/requirements", { title, body, repo, base_branch: branch }),
    onSuccess: ({ id }) => {
      client.invalidateQueries({ queryKey: ["requirements"] });
      navigate(`/requirements/${id}`);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Card className="mb-7 animate-rise p-5">
      <form onSubmit={submit} className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl font-medium">New requirement</h2>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-ink-3 hover:bg-sunken"><X className="size-4" /></button>
        </div>
        <Field label="Title">
          <input required minLength={3} value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} />
        </Field>
        <Field label="What should change, and why?" hint="The planner reads this along with your repository.">
          <textarea required minLength={10} rows={4} value={body} onChange={(e) => setBody(e.target.value)} className={inputClass} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
          <div>
            <span className="mb-1.5 block text-sm font-semibold">Repository</span>
            <RepoPicker value={repo} onChange={(name, defaultBranch) => { setRepo(name); if (defaultBranch) setBranch(defaultBranch); }} />
          </div>
          <Field label="Base branch">
            <input required value={branch} onChange={(e) => setBranch(e.target.value)} className={`${inputClass} font-mono`} />
          </Field>
        </div>
        <ErrorNote error={create.error} />
        <Button type="submit" variant="primary" busy={create.isPending}>Send to the planner</Button>
      </form>
    </Card>
  );
}

export default function Requirements() {
  const [adding, setAdding] = useState(false);
  const { data, error, isLoading } = useQuery({
    queryKey: ["requirements"],
    queryFn: () => get<RequirementRow[]>("/requirements"),
    refetchInterval: 3000,
  });
  return (
    <div className="">
      <PageHeader eyebrow="Requirements" title="What the team is building">
        <Button variant="primary" onClick={() => setAdding(true)}><FilePlus2 className="size-4" /> New requirement</Button>
      </PageHeader>
      {adding && <NewRequirement onClose={() => setAdding(false)} />}
      {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : data?.length === 0 ? (
        !adding && (
          <EmptyState icon={<FilePlus2 className="size-5" />} title="No requirements yet">
            Describe a change and the agents will break it into tasks for you to approve.
          </EmptyState>
        )
      ) : (
        <Card className="divide-y divide-line overflow-hidden">
          {data?.map((r) => (
            <Link key={r.id} to={`/requirements/${r.id}`} className="group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-paper/70">
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{r.title}</span>
                  <StatusBadge status={r.status} />
                  {r.awaiting > 0 && <Badge tone="gold">{r.awaiting} to approve</Badge>}
                </span>
                <span className="mt-1 block text-xs text-ink-3">
                  <span className="font-mono">{r.repo}</span> · filed by {r.created_by} · {timeAgo(r.created_at)}
                </span>
              </span>
              {r.task_count > 0 && (
                <span className="w-24 shrink-0 max-sm:hidden">
                  <span className="mb-1 block text-right text-xs text-ink-2 tabular-nums">{r.tasks_done} of {r.task_count} tasks</span>
                  <span className="block h-1.5 overflow-hidden rounded-full bg-sunken">
                    <span className="block h-full rounded-full bg-moss" style={{ width: `${(r.tasks_done / r.task_count) * 100}%` }} />
                  </span>
                </span>
              )}
              <ChevronRight className="size-4 shrink-0 text-ink-3 transition-transform group-hover:translate-x-0.5" />
            </Link>
          ))}
        </Card>
      )}
    </div>
  );
}
