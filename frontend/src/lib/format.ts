export function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export const dollars = (value: number) =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: value < 1 ? 3 : 2 }).format(value);

export const clockTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const fullTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });

export const compactNumber = (n: number) =>
  new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);

export const shortHash = (hash: string, length = 10) => hash.slice(0, length);

const ACTIONS: Record<string, string> = {
  "requirement.created": "Filed a requirement",
  "run.requested": "Started an agent",
  "run.started": "Began work",
  "run.completed": "Finished work",
  "run.failed": "Run failed",
  "llm.turn": "Model turn",
  "tool.called": "Used a tool",
  "proposal.created": "Submitted a proposal",
  "proposal.edited": "Edited a proposal",
  "proposal.approved": "Approved",
  "proposal.rejected": "Rejected",
  "proposal.changes_requested": "Requested changes",
  "proposal.retried": "Retried GitHub action",
  "tasks.created": "Created tasks from plan",
  "github.pr_opened": "Opened a pull request",
  "github.review_posted": "Posted a PR review",
  "github.write_failed": "GitHub action failed",
  "audit.verified": "Verified the audit chain",
  "audit.exported": "Exported the audit log",
  "setup.completed": "Set up Countersign",
  "auth.password_changed": "Changed their password",
  "user.removed": "Removed an approver",
  "memory.added": "Added team guidance",
  "memory.updated": "Updated team guidance",
  "memory.learned": "Learned from a review note",
  "memory.applied": "Applied team guidance",
  "settings.notifications_updated": "Updated notifications",
  "settings.tracker_updated": "Updated tracker secrets",
  "settings.tracker_linked": "Linked a tracker project",
  "settings.tracker_unlinked": "Unlinked a tracker project",
  "compliance.exported": "Exported an evidence pack",
  "auth.signed_in": "Signed in",
  "auth.password_reset": "Reset a password",
  "user.added": "Added an approver",
  "settings.credentials_updated": "Updated credentials",
  "run.stop_requested": "Asked an agent to stop",
  "run.recovered": "Recovered a run from a lost worker",
  "run.retrying": "Scheduled a retry",
  "run.released": "Returned a run to the queue",
  "settings.github_app_connected": "Connected the GitHub App",
};

export const actionLabel = (action: string) => ACTIONS[action] ?? action;

export const AGENT_LABEL: Record<string, string> = {
  planner: "Planner",
  coder: "Coder",
  tester: "Tester",
  reviewer: "Reviewer",
};

export function stepLabel(tool: string, path: string | null): string {
  if (tool === "read_file") return `Reading ${path}`;
  if (tool === "list_files") return path ? `Browsing ${path}` : "Browsing the repository";
  if (tool === "submit") return "Submitting for your approval";
  return tool;
}
