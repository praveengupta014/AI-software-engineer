const TOKEN_KEY = "countersign.token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (token: string) => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export async function signOut(): Promise<void> {
  await post("/auth/logout").catch(() => undefined);
  clearToken();
  window.location.assign("/");
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      ...init.headers,
    },
  });
  if (response.status === 401 && getToken() && path !== "/auth/login") {
    clearToken();
    window.location.assign("/");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail?.[0]?.msg;
    throw new ApiError(response.status, message ?? `Request failed (${response.status})`);
  }
  return response;
}

export const get = async <T,>(path: string): Promise<T> => (await request(path)).json();

export const remove = async <T,>(path: string): Promise<T> =>
  (await request(path, { method: "DELETE" })).json();

export const post = async <T,>(path: string, body?: unknown, method = "POST"): Promise<T> =>
  (await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) })).json();

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export async function downloadAudit(): Promise<void> {
  saveBlob(await (await request("/audit/export")).blob(), "countersign-audit.jsonl");
}

export async function downloadEvidence(start: string, end: string): Promise<void> {
  const params = new URLSearchParams({ start, end });
  const blob = await (await request(`/compliance/export?${params}`)).blob();
  saveBlob(blob, `countersign-evidence-${start}-to-${end}.zip`);
}

export type Health = {
  status: string;
  configured: boolean;
  needs: { anthropic_key: boolean; github_token: boolean };
};

export type Repo = { full_name: string; default_branch: string; private: boolean; description: string };
export type OpenPull = { number: number; title: string; author: string };

export type Settings = {
  model: string;
  anthropic: { ok: boolean; problem: string | null };
  github: { ok: boolean; problem: string | null; login: string | null; mode: "app" | "token"; install_url: string | null };
  webhooks: { configured: boolean; path: string; issue_label: string };
  workers: { id: string; last_seen: string }[];
  notifications: { slack: boolean; teams: boolean; public_url: string; failed: number };
  trackers: {
    jira_secret: boolean;
    linear_secret: boolean;
    label: string;
    links: { id: string; provider: "jira" | "linear"; project_key: string; repo: string; base_branch: string }[];
  };
  users: { name: string; created_at: string }[];
};

export type DataSummary = {
  tables: { key: string; label: string; count: number }[];
  storage: { kind: "sqlite" | "postgresql"; path: string; size_bytes: number };
};

export type DataPage = {
  columns: string[];
  primary_key: string;
  rows: Payload[];
  total: number;
  page: number;
  page_size: number;
};

export type Outcomes = {
  decided: number;
  approved_as_is: number;
  approved_after_edit: number;
  sent_back: number;
  rejected: number;
};

export type Insights = {
  days: number;
  overview: Outcomes & {
    approval_rate: number | null;
    as_is_rate: number | null;
    median_decision_seconds: number | null;
    estimated_cost: number;
    average_pr_cost: number | null;
    failed_runs: number;
    total_runs: number;
  };
  by_kind: (Outcomes & { kind: string })[];
  by_agent: { agent: string; tokens: number; cost: number }[];
  pull_requests: { pr_number: number; pr_url: string; title: string; requirement: string; cost: number }[];
};

export type Memory = {
  id: string;
  repo: string;
  kind: "convention" | "lesson";
  applies_to: string | null;
  text: string;
  active: boolean;
  source_proposal_id: string | null;
  created_by: string;
  created_at: string;
};

export type RunStep = { seq: number; tool: string; path: string | null; is_error: boolean };

export type RiskFlag = { level: "high" | "medium"; code: string; message: string };

export type ProposalSummary = {
  id: string;
  kind: "plan" | "code" | "tests" | "pull_request" | "review";
  kind_label: string;
  title: string;
  repo: string;
  status: "pending" | "approved" | "executed" | "failed" | "rejected" | "changes_requested";
  run_id: string | null;
  requirement_id: string | null;
  task_id: string | null;
  payload_hash: string;
  revision: number;
  edited_by: string | null;
  risk_flags: RiskFlag[];
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  external_url: string | null;
  error: string | null;
  created_at: string;
  summary: string | null;
  file_count: number;
};

export type FileChange = {
  path: string;
  action: "create" | "update" | "delete";
  content: string;
  diff: string;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Payload = Record<string, any>;

export type AuditEvent = {
  seq: number;
  ts: string;
  actor_type: "agent" | "human" | "system";
  actor: string;
  action: string;
  subject_type: string;
  subject_id: string;
  requirement_id: string | null;
  data: Payload;
  prev_hash: string;
  hash: string;
};

export type Run = {
  id: string;
  agent: string;
  repo: string;
  requirement_id: string | null;
  task_id: string | null;
  pr_number: number | null;
  status: "queued" | "running" | "done" | "failed";
  model: string | null;
  turns: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  error: string | null;
  created_at: string;
  stop_requested_by: string | null;
  steps?: RunStep[];
};

export type Proposal = ProposalSummary & {
  payload: Payload;
  run: Run | null;
  events: AuditEvent[];
};

export type Task = {
  id: string;
  position: number;
  title: string;
  description: string;
  acceptance_criteria: string[];
  stage: "code" | "tests" | "pr" | "review" | "done";
  state: "idle" | "running" | "awaiting_approval" | "blocked" | "done";
  pr_number: number | null;
  pr_url: string | null;
};

export type Requirement = {
  id: string;
  title: string;
  body: string;
  repo: string;
  base_branch: string;
  status: "planning" | "in_progress" | "done" | "rejected" | "failed";
  created_by: string;
  created_at: string;
  source_url: string | null;
};

export type RequirementRow = Requirement & { task_count: number; tasks_done: number; awaiting: number };
export type RequirementDetail = Requirement & { tasks: Task[]; proposals: ProposalSummary[]; runs: Run[] };

export type Overview = {
  pending: ProposalSummary[];
  active_runs: Run[];
  recent_events: AuditEvent[];
  stats: {
    awaiting: number;
    executed: number;
    sent_back: number;
    failed: number;
    audit_events: number;
    input_tokens: number;
    output_tokens: number;
  };
};

export type VerifyResult = {
  ok: boolean;
  checked: number;
  first_bad_seq: number | null;
  reason: string | null;
  head: string | null;
};
