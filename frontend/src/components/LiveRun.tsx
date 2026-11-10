import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Bot, Check, LoaderCircle, Square } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { post, type Run } from "../lib/api";
import { AGENT_LABEL, compactNumber, stepLabel } from "../lib/format";
import { Button, Card, cx } from "./ui";

/** Shows an agent working: real tool calls from the audit trail, as they happen. */
export function LiveRun({ run, compact }: { run: Run; compact?: boolean }) {
  const client = useQueryClient();
  const stop = useMutation({
    mutationFn: () => post(`/runs/${run.id}/stop`),
    onSuccess: () => client.invalidateQueries(),
  });
  const steps = run.steps ?? [];
  const stopping = !!run.stop_requested_by;
  const tokens = run.input_tokens + run.output_tokens;

  return (
    <Card className={cx("overflow-hidden", compact ? "p-4" : "p-5")}>
      <div className="flex items-center gap-3">
        <span className="relative flex size-9 shrink-0 items-center justify-center rounded-xl bg-ocean-soft text-ocean">
          <Bot className="size-5" />
          <span className="absolute -top-0.5 -right-0.5 flex size-2.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-ocean/60" />
            <span className="relative inline-flex size-2.5 rounded-full bg-ocean" />
          </span>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{AGENT_LABEL[run.agent]} {run.status === "queued" ? "is waiting for a worker" : "is working"}</p>
          <p className="truncate font-mono text-xs text-ink-3">
            {run.repo}{run.turns > 0 ? ` · ${run.turns} turns · ${compactNumber(tokens)} tokens` : ""}
          </p>
        </div>
        <Button busy={stop.isPending} disabled={stopping} onClick={() => stop.mutate()} className="!px-2.5 !py-1.5 !text-xs">
          <Square className="size-3" /> {stopping ? "Stopping" : "Stop"}
        </Button>
      </div>
      <ol className="mt-3.5 space-y-1.5 border-t border-line pt-3">
        {steps.length === 0 && (
          <li className="flex items-center gap-2 text-[13px] text-ink-2"><LoaderCircle className="size-3.5 animate-spin" /> {run.status === "queued" ? "In the queue" : "Thinking"}</li>
        )}
        <AnimatePresence initial={false}>
          {steps.slice(compact ? -3 : -6).map((step, index, shown) => (
            <motion.li
              key={step.seq}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex min-w-0 items-center gap-2 text-[13px] text-ink-2"
            >
              {step.is_error ? <AlertCircle className="size-3.5 shrink-0 text-clay" />
                : index === shown.length - 1 ? <LoaderCircle className="size-3.5 shrink-0 animate-spin text-ocean" />
                : <Check className="size-3.5 shrink-0 text-moss" />}
              <span className="truncate">{stepLabel(step.tool, step.path)}</span>
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
    </Card>
  );
}
