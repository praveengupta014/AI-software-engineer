import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Table2 } from "lucide-react";
import { useState } from "react";
import { Card, EmptyState, ErrorNote, Loading, PageHeader, SectionTitle, cx } from "../components/ui";
import { get, type Insights as Data, type Outcomes } from "../lib/api";
import { AGENT_LABEL, dollars, formatDuration } from "../lib/format";

// Validated with the dataviz palette script: colour-blind separation, contrast and order.
const SERIES = [
  { key: "approved_as_is", label: "Approved as is", color: "#1baf7a" },
  { key: "approved_after_edit", label: "Approved after edits", color: "#2a78d6" },
  { key: "sent_back", label: "Sent back", color: "#eda100" },
  { key: "rejected", label: "Rejected", color: "#b23f2b" },
] as const;

const KIND_LABEL: Record<string, string> = { plan: "Plans", code: "Code", tests: "Tests", pull_request: "Pull requests", review: "Reviews" };
const RANGES = [7, 30, 90];

type Tip = { x: number; y: number; title: string; lines: string[] } | null;

const percent = (value: number | null) => (value === null ? "—" : `${Math.round(value * 100)}%`);

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="font-serif text-[1.9rem] leading-tight font-medium tabular-nums">{value}</div>
      <div className="mt-0.5 text-[13px] font-medium">{label}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-3">{hint}</div>}
    </Card>
  );
}

function Legend() {
  return (
    <ul className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2">
      {SERIES.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: s.color }} /> {s.label}
        </li>
      ))}
    </ul>
  );
}

function OutcomeBars({ rows, onTip }: { rows: Data["by_kind"]; onTip: (tip: Tip) => void }) {
  const widest = Math.max(1, ...rows.map((r) => r.decided));
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.kind} className="grid grid-cols-[6.5rem_1fr_2rem] items-center gap-3 text-[13px]">
          <span className="text-ink-2">{KIND_LABEL[row.kind] ?? row.kind}</span>
          <div className="flex h-5 gap-0.5" style={{ width: `${Math.max(2, (row.decided / widest) * 100)}%` }}>
            {row.decided === 0 && <span className="h-full w-full rounded bg-sunken" />}
            {SERIES.map((s) => {
              const value = row[s.key as keyof Outcomes];
              return value > 0 ? (
                <span
                  key={s.key}
                  className="h-full first:rounded-l last:rounded-r"
                  style={{ flexGrow: value, flexBasis: 0, background: s.color }}
                  onMouseMove={(e) => onTip({ x: e.clientX, y: e.clientY, title: KIND_LABEL[row.kind] ?? row.kind, lines: [`${s.label}: ${value} of ${row.decided}`] })}
                  onMouseLeave={() => onTip(null)}
                />
              ) : null;
            })}
          </div>
          <span className="text-right text-ink-2 tabular-nums">{row.decided}</span>
        </div>
      ))}
    </div>
  );
}

function OutcomeTable({ rows }: { rows: Data["by_kind"] }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead><tr className="text-xs text-ink-3">
          <th scope="col" className="py-1.5 pr-3 font-semibold">Type</th>
          {SERIES.map((s) => <th key={s.key} scope="col" className="px-3 py-1.5 text-right font-semibold">{s.label}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.kind} className="border-t border-line">
              <td className="py-1.5 pr-3">{KIND_LABEL[row.kind] ?? row.kind}</td>
              {SERIES.map((s) => <td key={s.key} className="px-3 py-1.5 text-right tabular-nums">{row[s.key as keyof Outcomes]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RankedBars({ rows, onTip }: { rows: { key: string; label: string; href?: string; value: number; detail: string }[]; onTip: (tip: Tip) => void }) {
  const largest = Math.max(...rows.map((r) => r.value), 0.0001);
  return (
    <ol className="space-y-2.5">
      {rows.map((row) => (
        <li key={row.key} className="text-[13px]">
          <div className="mb-1 flex items-baseline justify-between gap-3">
            {row.href ? (
              <a href={row.href} target="_blank" rel="noreferrer" className="inline-flex min-w-0 items-center gap-1 hover:underline">
                <span className="truncate">{row.label}</span> <ExternalLink className="size-3 shrink-0 text-ink-3" />
              </a>
            ) : <span className="truncate">{row.label}</span>}
            <span className="shrink-0 font-medium tabular-nums">{dollars(row.value)}</span>
          </div>
          <div
            className="h-2 rounded-r bg-[#2a78d6]"
            style={{ width: `${Math.max(1.5, (row.value / largest) * 100)}%` }}
            onMouseMove={(e) => onTip({ x: e.clientX, y: e.clientY, title: row.label, lines: [dollars(row.value), row.detail] })}
            onMouseLeave={() => onTip(null)}
          />
        </li>
      ))}
    </ol>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const [asTable, setAsTable] = useState(false);
  const [tip, setTip] = useState<Tip>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["insights", days],
    queryFn: () => get<Data>(`/insights?days=${days}`),
    refetchInterval: 15000,
  });

  return (
    <div>
      <PageHeader eyebrow="Insights" title="How the agents are doing">
        <div role="group" aria-label="Time range" className="flex rounded-lg border border-line-strong bg-surface p-0.5">
          {RANGES.map((range) => (
            <button key={range} aria-pressed={days === range} onClick={() => setDays(range)} className={cx("rounded-md px-2.5 py-1 text-[13px] font-medium transition-colors", days === range ? "bg-ink text-paper" : "text-ink-2 hover:text-ink")}>
              {range} days
            </button>
          ))}
        </div>
      </PageHeader>

      {isLoading ? <Loading /> : !data ? <ErrorNote error={error} /> : data.overview.decided === 0 && data.overview.total_runs === 0 ? (
        <EmptyState icon={<Table2 className="size-5" />} title="Nothing to measure yet">
          Numbers appear here once agents have finished work and people have decided on it.
        </EmptyState>
      ) : (
        <>
          <div className="mb-8 grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-3">
            <Tile label="Approval rate" value={percent(data.overview.approval_rate)} hint={`${data.overview.decided} decisions on agent work`} />
            <Tile label="Approved without edits" value={percent(data.overview.as_is_rate)} hint="Of everything approved" />
            <Tile label="Median time to decide" value={data.overview.median_decision_seconds === null ? "—" : formatDuration(data.overview.median_decision_seconds)} />
            <Tile label="Estimated cost" value={dollars(data.overview.estimated_cost)} hint={data.overview.average_pr_cost === null ? `${data.overview.total_runs} agent runs` : `About ${dollars(data.overview.average_pr_cost)} per PR`} />
          </div>

          <div className="grid gap-5 lg:grid-cols-2 [&>*]:min-w-0">
            <Card className="p-5 lg:col-span-2">
              <SectionTitle aside={
                <button onClick={() => setAsTable(!asTable)} className="inline-flex items-center gap-1 hover:text-ink">
                  <Table2 className="size-3.5" /> {asTable ? "Show chart" : "Show table"}
                </button>
              }>What happened to each kind of work</SectionTitle>
              {data.by_kind.length === 0 ? <p className="text-sm text-ink-3">No decisions yet.</p>
                : asTable ? <OutcomeTable rows={data.by_kind} />
                : <><Legend /><OutcomeBars rows={data.by_kind} onTip={setTip} /></>}
            </Card>

            <Card className="p-5">
              <SectionTitle aside="Most expensive first">Cost per pull request</SectionTitle>
              {data.pull_requests.length === 0 ? <p className="text-sm text-ink-3">No pull requests yet.</p> : (
                <RankedBars
                  onTip={setTip}
                  rows={data.pull_requests.map((pr) => ({ key: String(pr.pr_number), label: `#${pr.pr_number} ${pr.title}`, href: pr.pr_url, value: pr.cost, detail: pr.requirement }))}
                />
              )}
            </Card>

            <Card className="p-5">
              <SectionTitle aside={`${data.overview.failed_runs} of ${data.overview.total_runs} runs failed`}>Cost by agent</SectionTitle>
              {data.by_agent.length === 0 ? <p className="text-sm text-ink-3">No agent runs yet.</p> : (
                <RankedBars
                  onTip={setTip}
                  rows={data.by_agent.map((a) => ({ key: a.agent, label: AGENT_LABEL[a.agent], value: a.cost, detail: `${a.tokens.toLocaleString()} tokens` }))}
                />
              )}
            </Card>
          </div>
          <p className="mt-4 text-xs leading-relaxed text-ink-3">
            Costs are estimates from token counts and list prices, so your Anthropic invoice is the source of truth. Pull request cost covers code, tests and review, but not the plan, which tasks share.
          </p>
        </>
      )}

      {tip && (
        <div role="tooltip" className="pointer-events-none fixed z-40 max-w-64 rounded-lg bg-ink px-2.5 py-1.5 text-xs text-paper shadow-lg" style={{ left: tip.x + 12, top: tip.y + 12 }}>
          <p className="font-semibold">{tip.title}</p>
          {tip.lines.map((line) => <p key={line} className="text-paper/75">{line}</p>)}
        </div>
      )}
    </div>
  );
}
