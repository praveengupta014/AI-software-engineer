import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { RepoPicker } from "../components/RepoPicker";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Loading, PageHeader, cx, inputClass } from "../components/ui";
import { get, post, type Memory as Item } from "../lib/api";
import { AGENT_LABEL, timeAgo } from "../lib/format";

type Data = { repos: string[]; items: Item[] };

function Row({ item }: { item: Item }) {
  const client = useQueryClient();
  const toggle = useMutation({
    mutationFn: () => post(`/memory/${item.id}`, { active: !item.active }, "PUT"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["memory"] }),
  });
  return (
    <li className={cx("flex items-start gap-3 px-5 py-3.5", !item.active && "opacity-55")}>
      <div className="min-w-0 flex-1">
        <p className="text-sm leading-relaxed">{item.text}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
          <Badge tone={item.kind === "convention" ? "ocean" : "gold"}>
            {item.kind === "convention" ? "Convention, all agents" : `Lesson for ${AGENT_LABEL[item.applies_to ?? ""] ?? "agents"}`}
          </Badge>
          <span className="font-mono">{item.repo}</span>
          <span>{item.created_by} · {timeAgo(item.created_at)}</span>
          {item.source_proposal_id && <Link to={`/proposals/${item.source_proposal_id}`} className="hover:text-ink hover:underline">From a review</Link>}
        </p>
      </div>
      <Button busy={toggle.isPending} onClick={() => toggle.mutate()} className="!px-2.5 !py-1.5 !text-xs">
        {item.active ? "Turn off" : "Turn on"}
      </Button>
    </li>
  );
}

export default function Memory() {
  const [repo, setRepo] = useState("");
  const [text, setText] = useState("");
  const [filter, setFilter] = useState("");
  const client = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: ["memory", filter],
    queryFn: () => get<Data>(`/memory${filter ? `?repo=${encodeURIComponent(filter)}` : ""}`),
  });
  const add = useMutation({
    mutationFn: () => post("/memory", { repo, text }),
    onSuccess: () => { setText(""); client.invalidateQueries({ queryKey: ["memory"] }); },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };

  return (
    <div>
      <PageHeader eyebrow="Memory" title="What your team has taught the agents" />
      <p className="-mt-3 mb-6 max-w-2xl text-[15px] leading-relaxed text-ink-2">
        Notes you leave when rejecting or sending back work are kept for that repository and agent, so the same mistake is not repeated. Only people write here, never agents.
      </p>

      <Card className="mb-7 p-5">
        <form onSubmit={submit} className="space-y-3">
          <div>
            <span className="mb-1.5 block text-sm font-semibold">Repository</span>
            <RepoPicker value={repo} onChange={(name) => setRepo(name)} />
          </div>
          <Field label="Add a convention" hint="Every agent working on this repository will follow it.">
            <textarea required minLength={3} maxLength={1000} rows={2} placeholder="All money values use decimal.Decimal, never float." value={text} onChange={(e) => setText(e.target.value)} className={inputClass} />
          </Field>
          <ErrorNote error={add.error} />
          <Button type="submit" variant="primary" busy={add.isPending}><Plus className="size-4" /> Add convention</Button>
        </form>
      </Card>

      {data && data.repos.length > 1 && (
        <div className="mb-3 max-w-xs">
          <select aria-label="Filter by repository" value={filter} onChange={(e) => setFilter(e.target.value)} className={inputClass}>
            <option value="">All repositories</option>
            {data.repos.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      )}
      {isLoading ? <Loading /> : !data ? <ErrorNote error={error} /> : data.items.length === 0 ? (
        <EmptyState icon={<BrainCircuit className="size-5" />} title="Nothing learned yet">
          Add a convention above, or reject a proposal with a note.
        </EmptyState>
      ) : (
        <Card className="overflow-hidden"><ul className="divide-y divide-line">{data.items.map((item) => <Row key={item.id} item={item} />)}</ul></Card>
      )}
    </div>
  );
}
