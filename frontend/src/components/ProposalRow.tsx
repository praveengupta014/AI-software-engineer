import { ChevronRight, ClipboardList, Code2, FlaskConical, GitPullRequest, MessageSquareText, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import type { ProposalSummary } from "../lib/api";
import { timeAgo } from "../lib/format";
import { Badge, StatusBadge } from "./ui";

export const KIND_ICON = {
  plan: ClipboardList,
  code: Code2,
  tests: FlaskConical,
  pull_request: GitPullRequest,
  review: MessageSquareText,
};

export function ProposalRow({ proposal, showStatus }: { proposal: ProposalSummary; showStatus?: boolean }) {
  const Icon = KIND_ICON[proposal.kind];
  const high = proposal.risk_flags.filter((f) => f.level === "high").length;
  return (
    <Link
      to={`/proposals/${proposal.id}`}
      className="group flex items-start gap-3.5 px-5 py-4 transition-colors hover:bg-gold-soft/30"
    >
      <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-sunken text-ink-2">
        <Icon className="size-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{proposal.title}</span>
          {high > 0 && (
            <Badge tone="clay">
              <TriangleAlert className="size-3" /> High risk
            </Badge>
          )}
          {showStatus && <StatusBadge status={proposal.status} />}
        </span>
        <span className="mt-0.5 line-clamp-1 block text-sm text-ink-2">{proposal.summary}</span>
        <span className="mt-1 block text-xs text-ink-3">
          {proposal.kind_label} · <span className="font-mono">{proposal.repo}</span> · {timeAgo(proposal.created_at)}
        </span>
      </span>
      <ChevronRight className="mt-2 size-4 shrink-0 text-ink-3 transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}
