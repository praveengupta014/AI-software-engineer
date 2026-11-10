import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitPullRequest } from "lucide-react";
import { useState, type FormEvent } from "react";
import { LiveRun } from "../components/LiveRun";
import { ProposalRow } from "../components/ProposalRow";
import { RepoPicker } from "../components/RepoPicker";
import { Button, Card, EmptyState, ErrorNote, Field, Loading, PageHeader, SectionTitle, inputClass } from "../components/ui";
import { get, post, type OpenPull, type ProposalSummary, type Run } from "../lib/api";

type Data = { proposals: ProposalSummary[]; runs: Run[] };

export default function Reviews() {
  const [repo, setRepo] = useState("");
  const [number, setNumber] = useState("");
  const repoReady = /^[\w.-]+\/[\w.-]+$/.test(repo);
  const pulls = useQuery({
    queryKey: ["github-pulls", repo],
    queryFn: () => get<OpenPull[]>(`/github/repos/${repo}/pulls`),
    enabled: repoReady,
    retry: false,
  });
  const client = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: ["reviews"],
    queryFn: () => get<Data>("/reviews"),
    refetchInterval: 2000,
  });
  const request = useMutation({
    mutationFn: () => post("/reviews", { repo, pr_number: Number(number) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["reviews"] }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    request.mutate();
  };
  const active = data?.runs.filter((r) => r.status === "queued" || r.status === "running") ?? [];
  const failed = data?.runs.filter((r) => r.status === "failed").slice(0, 3) ?? [];

  return (
    <div className="">
      <PageHeader eyebrow="PR reviews" title="Review any pull request" />
      <Card className="mb-8 p-5">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
          <div className="min-w-56 flex-1">
            <span className="mb-1.5 block text-sm font-semibold">Repository</span>
            <RepoPicker value={repo} onChange={(name) => { setRepo(name); setNumber(""); }} />
          </div>
          <div className="min-w-56 flex-1">
            <Field label="Pull request">
              <select required value={number} onChange={(e) => setNumber(e.target.value)} disabled={!pulls.data?.length} className={inputClass}>
                <option value="">
                  {!repoReady ? "Choose a repository first" : pulls.isLoading ? "Loading" : pulls.data?.length ? "Choose a pull request" : "No open pull requests"}
                </option>
                {pulls.data?.map((p) => <option key={p.number} value={p.number}>#{p.number} {p.title}</option>)}
              </select>
            </Field>
          </div>
          <Button type="submit" variant="primary" busy={request.isPending}>Ask the reviewer</Button>
        </form>
        <p className="mt-3 text-[13px] text-ink-3">The reviewer drafts comments here first. Nothing is posted to GitHub until you approve it.</p>
        <div className="mt-3"><ErrorNote error={request.error ?? pulls.error} /></div>
      </Card>

      <div className="space-y-3">{active.map((run) => <div key={run.id} className="mb-4"><LiveRun run={run} /></div>)}</div>
      {failed.map((run) => (
        <p key={run.id} className="mb-4 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">
          <span className="font-mono">{run.repo}#{run.pr_number}</span>: {run.error}
        </p>
      ))}

      {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : data?.proposals.length === 0 ? (
        active.length === 0 && (
          <EmptyState icon={<GitPullRequest className="size-5" />} title="No reviews yet">
            Reviews of pull requests Countersign opened itself appear on their requirement.
          </EmptyState>
        )
      ) : (
        <section>
          <SectionTitle>Reviews</SectionTitle>
          <Card className="divide-y divide-line overflow-hidden">
            {data?.proposals.map((p) => <ProposalRow key={p.id} proposal={p} showStatus />)}
          </Card>
        </section>
      )}
    </div>
  );
}
