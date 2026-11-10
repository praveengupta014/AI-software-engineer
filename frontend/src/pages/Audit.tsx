import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BookText, ChevronDown, Download, FileArchive, Link2, ShieldCheck, ShieldX } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { ActorChip } from "../components/ActorChip";
import { Button, Card, EmptyState, ErrorNote, Field, Loading, PageHeader, cx, inputClass } from "../components/ui";
import { downloadAudit, downloadEvidence, get, type AuditEvent, type VerifyResult } from "../lib/api";
import { actionLabel, fullTime, shortHash } from "../lib/format";

type Page = { events: AuditEvent[]; next_before_seq: number | null };

const ACTORS = [
  { value: "", label: "Everyone" },
  { value: "human", label: "People" },
  { value: "agent", label: "Agents" },
  { value: "system", label: "System" },
];
const ACTIONS = [
  { value: "", label: "All actions" },
  { value: "proposal.", label: "Proposals and decisions" },
  { value: "github.", label: "GitHub writes" },
  { value: "tool.", label: "Tool calls" },
  { value: "llm.", label: "Model turns" },
  { value: "run.", label: "Agent runs" },
];

function detail(e: AuditEvent): string {
  const d = e.data;
  if (e.action === "tool.called") return `${d.tool}${d.input?.path ? ` ${d.input.path}` : ""}`;
  if (e.action === "llm.turn") return `${(d.input_tokens ?? 0) + (d.output_tokens ?? 0)} tokens, ${d.stop_reason}`;
  if (d.title) return d.title;
  if (d.kind) return d.note ? `${d.kind}: ${d.note}` : d.kind;
  if (d.error) return d.error;
  if (d.url) return d.url;
  return "";
}

function subjectLink(e: AuditEvent) {
  if (e.subject_type === "proposal") return `/proposals/${e.subject_id}`;
  if (e.requirement_id) return `/requirements/${e.requirement_id}`;
  return null;
}

function Row({ event: e }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const link = subjectLink(e);
  return (
    <Fragment>
      <tr
        onClick={() => setOpen(!open)}
        className={cx("cursor-pointer border-t border-line transition-colors hover:bg-paper/70", e.actor_type === "human" && "bg-moss-soft/20")}
      >
        <td className="py-2.5 pr-3 pl-5 font-mono text-xs text-ink-3 tabular-nums">{e.seq}</td>
        <td className="px-3 py-2.5 font-mono text-xs whitespace-nowrap text-ink-2 max-md:hidden">{fullTime(e.ts)}</td>
        <td className="px-3 py-2.5"><ActorChip type={e.actor_type} name={e.actor} /></td>
        <td className="px-3 py-2.5 text-sm">
          <button aria-expanded={open} className="text-left font-medium">{actionLabel(e.action)}</button>
          <div className="line-clamp-1 max-w-md text-xs text-ink-3">{detail(e)}</div>
        </td>
        <td className="px-3 py-2.5 font-mono text-xs text-ink-3 max-lg:hidden">
          <span className="inline-flex items-center gap-1" title={e.hash}><Link2 className="size-3" />{shortHash(e.hash, 8)}</span>
        </td>
        <td className="pr-4"><ChevronDown className={cx("size-4 text-ink-3 transition-transform", open && "rotate-180")} /></td>
      </tr>
      {open && (
        <tr className="bg-paper/60">
          <td colSpan={6} className="px-5 pt-1 pb-4">
            <dl className="grid gap-x-4 gap-y-1 font-mono text-xs sm:grid-cols-[6rem_minmax(0,1fr)]">
              <dt className="text-ink-3">action</dt><dd>{e.action}</dd>
              <dt className="text-ink-3">subject</dt>
              <dd>{e.subject_type} {link ? <Link className="text-ocean hover:underline" to={link}>{e.subject_id}</Link> : e.subject_id}</dd>
              <dt className="text-ink-3">prev hash</dt><dd className="break-all">{e.prev_hash}</dd>
              <dt className="text-ink-3">hash</dt><dd className="break-all">{e.hash}</dd>
            </dl>
            {Object.keys(e.data).length > 0 && (
              <pre className="mt-3 overflow-x-auto rounded-lg bg-sunken p-3 font-mono text-xs leading-relaxed">{JSON.stringify(e.data, null, 2)}</pre>
            )}
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function VerifyBanner({ result }: { result: VerifyResult }) {
  return result.ok ? (
    <div className="mb-5 flex animate-rise items-start gap-3 rounded-xl bg-moss-soft p-4 text-moss">
      <ShieldCheck className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 text-sm">
        <p className="font-semibold">Chain intact. All {result.checked} events verified.</p>
        {result.head && <p className="mt-0.5 font-mono text-xs break-all">Head {result.head}</p>}
      </div>
    </div>
  ) : (
    <div className="mb-5 flex animate-rise items-start gap-3 rounded-xl bg-clay-soft p-4 text-clay">
      <ShieldX className="mt-0.5 size-5 shrink-0" />
      <p className="text-sm"><span className="font-semibold">Tampering detected at event {result.first_bad_seq}.</span> {result.reason}. {result.checked} earlier events are intact.</p>
    </div>
  );
}

const isoDate = (date: Date) => date.toISOString().slice(0, 10);

function EvidencePack({ onDone }: { onDone: () => void }) {
  const [start, setStart] = useState(() => isoDate(new Date(Date.now() - 90 * 86400_000)));
  const [end, setEnd] = useState(() => isoDate(new Date()));
  const pack = useMutation({ mutationFn: () => downloadEvidence(start, end), onSettled: onDone });
  return (
    <Card className="mb-7 p-5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-64 flex-1">
          <h2 className="flex items-center gap-2 font-semibold"><FileArchive className="size-4 text-gold" /> Evidence pack for audits</h2>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-ink-2">
            A signed ZIP of decisions, GitHub writes and access history, with automatic checks, suggested SOC 2 control references and any exceptions listed. It supports an audit but does not certify you.
          </p>
        </div>
        <div className="w-40"><Field label="From"><input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} className={inputClass} /></Field></div>
        <div className="w-40"><Field label="To"><input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} className={inputClass} /></Field></div>
        <Button busy={pack.isPending} onClick={() => pack.mutate()}>Download pack</Button>
      </div>
      <div className="mt-3"><ErrorNote error={pack.error} /></div>
    </Card>
  );
}

export default function Audit() {
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const client = useQueryClient();

  const log = useInfiniteQuery({
    queryKey: ["audit", actor, action],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "50" });
      if (actor) params.set("actor_type", actor);
      if (action) params.set("action", action);
      if (pageParam) params.set("before_seq", String(pageParam));
      return get<Page>(`/audit?${params}`);
    },
    getNextPageParam: (last) => last.next_before_seq,
    refetchInterval: 4000,
  });

  const verify = useMutation({
    mutationFn: () => get<VerifyResult>("/audit/verify"),
    onSettled: () => client.invalidateQueries({ queryKey: ["audit"] }),
  });

  const exportLog = useMutation({
    mutationFn: downloadAudit,
    onSettled: () => client.invalidateQueries({ queryKey: ["audit"] }),
  });

  const events = log.data?.pages.flatMap((p) => p.events) ?? [];

  return (
    <div>
      <PageHeader eyebrow="Audit trail" title="Every action, on the record">
        <Button busy={exportLog.isPending} onClick={() => exportLog.mutate()}><Download className="size-4" /> Export</Button>
        <Button variant="primary" busy={verify.isPending} onClick={() => verify.mutate()}><ShieldCheck className="size-4" /> Verify chain</Button>
      </PageHeader>
      <p className="-mt-3 mb-6 max-w-2xl text-[15px] leading-relaxed text-ink-2">
        Each entry is cryptographically linked to the one before it, so changing or removing any past entry breaks the chain from that point on.
      </p>

      <EvidencePack onDone={() => client.invalidateQueries({ queryKey: ["audit"] })} />
      {verify.data && <VerifyBanner result={verify.data} />}
      <ErrorNote error={verify.error ?? exportLog.error} />

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Filter by actor" className="flex rounded-lg border border-line-strong bg-surface p-0.5">
          {ACTORS.map((a) => (
            <button
              key={a.value}
              aria-pressed={actor === a.value}
              onClick={() => setActor(a.value)}
              className={cx("rounded-md px-2.5 py-1 text-[13px] font-medium transition-colors", actor === a.value ? "bg-ink text-paper" : "text-ink-2 hover:text-ink")}
            >
              {a.label}
            </button>
          ))}
        </div>
        <select
          aria-label="Filter by action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-[13px] font-medium text-ink-2"
        >
          {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
      </div>

      {log.isLoading ? <Loading /> : log.error ? <ErrorNote error={log.error} /> : events.length === 0 ? (
        <EmptyState icon={<BookText className="size-5" />} title="Nothing recorded here" />
      ) : (
        <Card className="overflow-hidden">
          <div className="relative overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="text-xs font-semibold text-ink-3">
                  <th scope="col" className="py-2.5 pr-3 pl-5 font-semibold">#</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold max-md:hidden">Time</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Actor</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Action</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold max-lg:hidden">Hash</th>
                  <th scope="col"><span className="sr-only">Details</span></th>
                </tr>
              </thead>
              <tbody>{events.map((e) => <Row key={e.seq} event={e} />)}</tbody>
            </table>
          </div>
          {log.hasNextPage && (
            <div className="border-t border-line p-3 text-center">
              <Button busy={log.isFetchingNextPage} onClick={() => log.fetchNextPage()}>Load older entries</Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
