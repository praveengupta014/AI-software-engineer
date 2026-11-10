import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCheck, CircleCheck, Coins, FileCheck2, Hourglass, Undo2 } from "lucide-react";
import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ActorChip } from "../components/ActorChip";
import { LiveRun } from "../components/LiveRun";
import { ProposalRow } from "../components/ProposalRow";
import { Card, EmptyState, ErrorNote, Loading, SectionTitle, cx } from "../components/ui";
import { get, type Overview as Data } from "../lib/api";
import { actionLabel, compactNumber, timeAgo } from "../lib/format";

function Count({ value }: { value: number }) {
  const motionValue = useMotionValue(0);
  const text = useTransform(motionValue, (v) => compactNumber(Math.round(v)));
  useEffect(() => {
    const controls = animate(motionValue, value, { duration: 0.7, ease: "easeOut" });
    return controls.stop;
  }, [motionValue, value]);
  return <motion.span>{text}</motion.span>;
}

function Stat({ label, value, icon, tint }: { label: string; value: number; icon: ReactNode; tint: string }) {
  return (
    <Card className="p-4 transition-transform hover:-translate-y-0.5">
      <span className={cx("mb-3 flex size-8 items-center justify-center rounded-lg", tint)}>{icon}</span>
      <div className="font-serif text-3xl font-medium tabular-nums"><Count value={value} /></div>
      <div className="mt-0.5 text-[13px] text-ink-2">{label}</div>
    </Card>
  );
}

export default function Overview() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["overview"],
    queryFn: () => get<Data>("/overview"),
    refetchInterval: 2000,
  });
  if (isLoading) return <Loading />;
  if (!data) return <ErrorNote error={error} />;

  const { stats, pending, active_runs: runs, recent_events: events } = data;
  const count = pending.length;
  const headline = count > 0
    ? `${count} ${count === 1 ? "decision is" : "decisions are"} waiting on you`
    : runs.length > 0 ? "Your agents are at work" : "Nothing needs you right now";

  return (
    <div>
      <section className="relative mb-6 overflow-hidden rounded-3xl bg-ink p-7 text-paper sm:p-9">
        <div className="aurora" />
        <div className="dot-grid absolute inset-0" />
        <div className="relative flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="mb-2 text-sm text-paper/60">Overview</p>
            <h1 className="max-w-xl font-serif text-[2.4rem] leading-[1.1] font-medium tracking-tight text-balance">{headline}</h1>
          </div>
          {count > 0 ? (
            <Link to={`/proposals/${pending[0].id}`} className="inline-flex items-center gap-2 rounded-xl bg-gold-bright px-4 py-2.5 text-sm font-bold text-ink transition-transform hover:-translate-y-0.5">
              Review the next one <ArrowRight className="size-4" />
            </Link>
          ) : (
            <Link to="/requirements" className="inline-flex items-center gap-2 rounded-xl bg-paper px-4 py-2.5 text-sm font-bold text-ink transition-transform hover:-translate-y-0.5">
              New requirement <ArrowRight className="size-4" />
            </Link>
          )}
        </div>
      </section>

      <div className="mb-9 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Awaiting approval" value={stats.awaiting} icon={<Hourglass className="size-4 text-gold" />} tint="bg-gold-soft" />
        <Stat label="Approved and carried out" value={stats.executed} icon={<FileCheck2 className="size-4 text-moss" />} tint="bg-moss-soft" />
        <Stat label="Rejected or sent back" value={stats.sent_back} icon={<Undo2 className="size-4 text-clay" />} tint="bg-clay-soft" />
        <Stat label="Tokens used" value={stats.input_tokens + stats.output_tokens} icon={<Coins className="size-4 text-ocean" />} tint="bg-ocean-soft" />
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20.5rem]">
        <section>
          <SectionTitle>Your approval queue</SectionTitle>
          {count === 0 ? (
            <EmptyState icon={<CheckCheck className="size-5" />} title="The queue is clear">
              When an agent finishes something, it waits here for your signature.
            </EmptyState>
          ) : (
            <Card className="divide-y divide-line overflow-hidden">
              {pending.map((p, index) => (
                <motion.div key={p.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }}>
                  <ProposalRow proposal={p} />
                </motion.div>
              ))}
            </Card>
          )}
        </section>

        <aside className="space-y-8">
          {runs.length > 0 && (
            <section>
              <SectionTitle>Agents at work</SectionTitle>
              <div className="space-y-3">{runs.map((run) => <LiveRun key={run.id} run={run} compact />)}</div>
            </section>
          )}
          <section>
            <SectionTitle aside={<Link to="/audit" className="hover:text-ink">Full trail</Link>}>Latest in the ledger</SectionTitle>
            {events.length === 0 ? (
              <p className="flex items-center gap-1.5 text-sm text-ink-3"><CircleCheck className="size-4" /> No activity yet.</p>
            ) : (
              <ol className="space-y-2.5">
                {events.slice(0, 7).map((e) => (
                  <li key={e.seq} className="flex items-start gap-2 text-[13px]">
                    <ActorChip type={e.actor_type} name={e.actor} />
                    <span className="min-w-0 pt-px text-ink-2">
                      {actionLabel(e.action)} <span className="whitespace-nowrap text-ink-3">· {timeAgo(e.ts)}</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
