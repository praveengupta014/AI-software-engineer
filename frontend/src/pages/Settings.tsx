import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, CheckCircle2, CircleAlert, Copy, Cpu, ExternalLink, KeyRound, Link2, Send, Trash2, UserPlus, Webhook, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button, Card, ErrorNote, Field, Loading, PageHeader, SectionTitle, inputClass } from "../components/ui";
import { RepoPicker } from "../components/RepoPicker";
import { get, post, remove, type Settings as Data } from "../lib/api";

function Connection({ title, ok, problem, detail, field, label, placeholder }: {
  title: string;
  ok: boolean;
  problem: string | null;
  detail: string;
  field: "anthropic_key" | "github_token";
  label: string;
  placeholder: string;
}) {
  const [value, setValue] = useState("");
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () => post("/settings/credentials", { [field]: value }, "PUT"),
    onSuccess: () => {
      setValue("");
      client.invalidateQueries({ queryKey: ["settings"] });
      client.invalidateQueries({ queryKey: ["github-repos"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-start gap-3">
        {ok ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-moss" /> : <CircleAlert className="mt-0.5 size-5 shrink-0 text-clay" />}
        <div>
          <h3 className="font-semibold">{title}</h3>
          <p className={`text-sm ${ok ? "text-ink-2" : "text-clay"}`}>{ok ? detail : problem}</p>
        </div>
      </div>
      <form onSubmit={submit} className="flex items-end gap-2">
        <div className="flex-1">
          <Field label={label}>
            <input type="password" autoComplete="off" required placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)} className={`${inputClass} font-mono`} />
          </Field>
        </div>
        <Button type="submit" busy={save.isPending}>Replace</Button>
      </form>
      <div className="mt-2"><ErrorNote error={save.error} /></div>
    </Card>
  );
}

function GitHubApp({ settings }: { settings: Data }) {
  const [appId, setAppId] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [copied, setCopied] = useState(false);
  const client = useQueryClient();
  const connected = settings.github.mode === "app";
  const webhookUrl = `${window.location.origin}${settings.webhooks.path}`;
  const save = useMutation({
    mutationFn: () => post("/settings/github-app", { app_id: appId, private_key: privateKey, webhook_secret: webhookSecret }, "PUT"),
    onSuccess: () => {
      setAppId("");
      setPrivateKey("");
      setWebhookSecret("");
      client.invalidateQueries({ queryKey: ["settings"] });
      client.invalidateQueries({ queryKey: ["github-repos"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const copy = async () => {
    await navigator.clipboard.writeText(webhookUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Card className="mb-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{connected ? "GitHub App connected" : "Connect a GitHub App"}</h3>
          <p className="mt-0.5 max-w-2xl text-sm leading-relaxed text-ink-2">
            Recommended for teams. Access is per repository, tokens expire within an hour, and commits appear under the app's name instead of a person's.
          </p>
        </div>
        {settings.github.install_url ? (
          <a href={settings.github.install_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-semibold text-ocean hover:underline">
            Choose repositories <ExternalLink className="size-3.5" />
          </a>
        ) : (
          <a href="https://github.com/settings/apps/new" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-semibold text-ocean hover:underline">
            Create an app <ExternalLink className="size-3.5" />
          </a>
        )}
      </div>

      <div className="mt-4 rounded-xl bg-sunken/70 p-3.5 text-sm leading-relaxed text-ink-2">
        <p className="mb-1 flex items-center gap-1.5 font-semibold text-ink"><Webhook className="size-4" /> Webhook {settings.webhooks.configured ? "secret is set" : "(optional)"}</p>
        <p>
          Give the app this URL to get automatic drafts: a review for each new pull request from your team, and a plan for each issue labelled <code className="font-mono text-[13px]">{settings.webhooks.issue_label}</code>. It must be reachable from the internet. Subscribe to <strong className="font-semibold text-ink">Pull requests</strong> and <strong className="font-semibold text-ink">Issues</strong>.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-lg bg-surface px-2.5 py-1.5 font-mono text-xs">{webhookUrl}</code>
          <Button type="button" onClick={copy} className="!px-2.5 !py-1.5 !text-xs">
            {copied ? <Check className="size-3.5 text-moss" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>

      <form onSubmit={submit} className="mt-4 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="App ID">
            <input required inputMode="numeric" autoComplete="off" value={appId} onChange={(e) => setAppId(e.target.value)} className={`${inputClass} font-mono`} />
          </Field>
          <Field label="Webhook secret" hint="The same value you gave GitHub">
            <input type="password" autoComplete="off" value={webhookSecret} onChange={(e) => setWebhookSecret(e.target.value)} className={`${inputClass} font-mono`} />
          </Field>
        </div>
        <Field label="Private key" hint="Paste the whole .pem file. It is never shown again.">
          <textarea required rows={3} spellCheck={false} autoComplete="off" placeholder="-----BEGIN RSA PRIVATE KEY-----" value={privateKey} onChange={(e) => setPrivateKey(e.target.value)} className={`${inputClass} font-mono text-xs`} />
        </Field>
        <ErrorNote error={save.error} />
        <Button type="submit" variant={connected ? "ghost" : "primary"} busy={save.isPending}>{connected ? "Replace the app" : "Connect the app"}</Button>
      </form>
    </Card>
  );
}

function Workers({ settings }: { settings: Data }) {
  const count = settings.workers.length;
  return (
    <section className="mb-9">
      <SectionTitle>Workers</SectionTitle>
      <Card className="flex items-start gap-3 p-5">
        <Cpu className={`mt-0.5 size-5 shrink-0 ${count ? "text-moss" : "text-clay"}`} />
        <div className="min-w-0 text-sm">
          <p className="font-semibold">{count ? `${count} ${count === 1 ? "worker" : "workers"} online` : "No workers online"}</p>
          <p className="text-ink-2">{count ? settings.workers.map((w) => w.id).join(", ") : "Agents wait in the queue until a worker starts."}</p>
        </div>
      </Card>
    </section>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const change = useMutation({
    mutationFn: () => post("/auth/change-password", { current_password: current, new_password: next }),
    onSuccess: () => { setCurrent(""); setNext(""); setRepeat(""); },
  });
  const mismatch = repeat.length > 0 && next !== repeat;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    change.mutate();
  };
  return (
    <section className="mb-9">
      <SectionTitle>Your password</SectionTitle>
      <Card className="p-5">
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-start">
          <Field label="Current password"><input required type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className={inputClass} /></Field>
          <Field label="New password" hint="At least 8 characters"><input required minLength={8} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className={inputClass} /></Field>
          <Field label="Repeat new password" hint={mismatch ? "These do not match" : undefined}><input required type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} className={inputClass} /></Field>
          <Button type="submit" busy={change.isPending} disabled={mismatch || !next || next !== repeat} className="sm:mt-[1.65rem]"><KeyRound className="size-4" /> Change</Button>
        </form>
        <div className="mt-2 space-y-2">
          <ErrorNote error={change.error} />
          {change.isSuccess && <p className="flex items-center gap-1.5 text-sm text-moss"><Check className="size-4" /> Password changed. Your other devices were signed out.</p>}
        </div>
      </Card>
    </section>
  );
}

function Notifications({ settings }: { settings: Data }) {
  const [publicUrl, setPublicUrl] = useState(settings.notifications.public_url || window.location.origin);
  const [slack, setSlack] = useState("");
  const [teams, setTeams] = useState("");
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () => post("/settings/notifications", { public_url: publicUrl, slack_url: slack, teams_url: teams }, "PUT"),
    onSuccess: () => { setSlack(""); setTeams(""); client.invalidateQueries({ queryKey: ["settings"] }); },
  });
  const test = useMutation({ mutationFn: (channel: string) => post("/settings/notifications/test", { channel }) });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const { slack: hasSlack, teams: hasTeams, failed } = settings.notifications;
  return (
    <section className="mb-9">
      <SectionTitle>Notifications</SectionTitle>
      <Card className="p-5">
        <p className="mb-4 flex items-start gap-2 text-sm leading-relaxed text-ink-2">
          <Bell className="mt-0.5 size-4 shrink-0 text-gold" />
          Post to a channel whenever something waits for approval, with a summary and a link to review it. Decisions still happen here.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Address of this app" hint="Used for the review links. Teammates must be able to open it.">
            <input required value={publicUrl} onChange={(e) => setPublicUrl(e.target.value)} className={`${inputClass} font-mono`} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={hasSlack ? "Slack webhook (connected)" : "Slack webhook URL"}>
              <input type="password" autoComplete="off" placeholder="https://hooks.slack.com/services/..." value={slack} onChange={(e) => setSlack(e.target.value)} className={`${inputClass} font-mono`} />
            </Field>
            <Field label={hasTeams ? "Teams webhook (connected)" : "Teams Workflows webhook URL"}>
              <input type="password" autoComplete="off" value={teams} onChange={(e) => setTeams(e.target.value)} className={`${inputClass} font-mono`} />
            </Field>
          </div>
          <ErrorNote error={save.error ?? test.error} />
          {failed > 0 && <p className="text-sm text-clay">{failed} message{failed === 1 ? "" : "s"} could not be delivered.</p>}
          {test.isSuccess && <p className="flex items-center gap-1.5 text-sm text-moss"><Check className="size-4" /> Test message sent.</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" busy={save.isPending}>Save</Button>
            {hasSlack && <Button type="button" busy={test.isPending && test.variables === "slack"} onClick={() => test.mutate("slack")}><Send className="size-4" /> Test Slack</Button>}
            {hasTeams && <Button type="button" busy={test.isPending && test.variables === "teams"} onClick={() => test.mutate("teams")}><Send className="size-4" /> Test Teams</Button>}
          </div>
        </form>
      </Card>
    </section>
  );
}

function Trackers({ settings }: { settings: Data }) {
  const [jiraSecret, setJiraSecret] = useState("");
  const [linearSecret, setLinearSecret] = useState("");
  const [provider, setProvider] = useState<"jira" | "linear">("jira");
  const [projectKey, setProjectKey] = useState("");
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["settings"] });
  const saveSecrets = useMutation({
    mutationFn: () => post("/settings/trackers", { jira_secret: jiraSecret, linear_secret: linearSecret }, "PUT"),
    onSuccess: () => { setJiraSecret(""); setLinearSecret(""); refresh(); },
  });
  const addLink = useMutation({
    mutationFn: () => post("/settings/tracker-links", { provider, project_key: projectKey, repo, base_branch: branch }),
    onSuccess: () => { setProjectKey(""); setRepo(""); refresh(); },
  });
  const removeLink = useMutation({ mutationFn: (id: string) => remove(`/settings/tracker-links/${id}`), onSuccess: refresh });
  const submitSecrets = (event: FormEvent) => { event.preventDefault(); saveSecrets.mutate(); };
  const submitLink = (event: FormEvent) => { event.preventDefault(); addLink.mutate(); };
  const origin = window.location.origin;
  const { trackers } = settings;
  return (
    <section className="mb-9">
      <SectionTitle>Jira and Linear</SectionTitle>
      <Card className="space-y-5 p-5">
        <p className="text-sm leading-relaxed text-ink-2">
          Add the label <code className="font-mono text-[13px]">{trackers.label}</code> to a ticket and it becomes a requirement. Each project below is tied to one repository, so a ticket can never choose where agents work. The webhook addresses must be reachable from the internet.
        </p>
        <div className="space-y-1 rounded-xl bg-sunken/70 p-3 font-mono text-xs break-all text-ink-2">
          <p>Jira: {origin}/api/webhooks/jira</p>
          <p>Linear: {origin}/api/webhooks/linear</p>
        </div>
        <form onSubmit={submitSecrets} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field label={trackers.jira_secret ? "Jira secret (set)" : "Jira webhook secret"}><input type="password" autoComplete="off" value={jiraSecret} onChange={(e) => setJiraSecret(e.target.value)} className={`${inputClass} font-mono`} /></Field>
          <Field label={trackers.linear_secret ? "Linear secret (set)" : "Linear signing secret"}><input type="password" autoComplete="off" value={linearSecret} onChange={(e) => setLinearSecret(e.target.value)} className={`${inputClass} font-mono`} /></Field>
          <Button type="submit" busy={saveSecrets.isPending}>Save secrets</Button>
        </form>
        <ErrorNote error={saveSecrets.error} />

        {trackers.links.length > 0 && (
          <ul className="divide-y divide-line rounded-xl border border-line">
            {trackers.links.map((link) => (
              <li key={link.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5 text-sm">
                <Link2 className="size-4 text-ink-3" />
                <span className="font-semibold capitalize">{link.provider}</span>
                <code className="font-mono text-[13px]">{link.project_key}</code>
                <span className="text-ink-3">→</span>
                <code className="min-w-0 truncate font-mono text-[13px]">{link.repo}@{link.base_branch}</code>
                <button aria-label={`Unlink ${link.project_key}`} onClick={() => removeLink.mutate(link.id)} className="ml-auto rounded p-1 text-ink-3 hover:bg-clay-soft hover:text-clay"><X className="size-4" /></button>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={submitLink} className="grid gap-3 sm:grid-cols-[8rem_9rem_1fr_8rem_auto] sm:items-end">
          <Field label="Tracker">
            <select value={provider} onChange={(e) => setProvider(e.target.value as "jira" | "linear")} className={inputClass}>
              <option value="jira">Jira</option>
              <option value="linear">Linear</option>
            </select>
          </Field>
          <Field label={provider === "jira" ? "Project key" : "Team key"}><input required placeholder={provider === "jira" ? "SHOP" : "ENG"} value={projectKey} onChange={(e) => setProjectKey(e.target.value)} className={`${inputClass} font-mono uppercase`} /></Field>
          <div>
            <span className="mb-1.5 block text-sm font-semibold">Repository</span>
            <RepoPicker value={repo} onChange={(name, defaultBranch) => { setRepo(name); if (defaultBranch) setBranch(defaultBranch); }} />
          </div>
          <Field label="Branch"><input required value={branch} onChange={(e) => setBranch(e.target.value)} className={`${inputClass} font-mono`} /></Field>
          <Button type="submit" busy={addLink.isPending}>Link</Button>
        </form>
        <ErrorNote error={addLink.error ?? removeLink.error} />
      </Card>
    </section>
  );
}

function RemoveApprover({ name }: { name: string }) {
  const [confirming, setConfirming] = useState(false);
  const client = useQueryClient();
  const drop = useMutation({
    mutationFn: () => remove(`/users/${encodeURIComponent(name)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["settings"] }),
  });
  if (!confirming) {
    return (
      <button aria-label={`Remove ${name}`} onClick={() => setConfirming(true)} className="rounded-full p-1 text-ink-3 hover:bg-clay-soft hover:text-clay">
        <Trash2 className="size-3.5" />
      </button>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <button disabled={drop.isPending} onClick={() => drop.mutate()} className="font-bold text-clay hover:underline">Remove</button>
      <button onClick={() => setConfirming(false)} className="text-ink-3 hover:underline">Keep</button>
    </span>
  );
}

function AddApprover() {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const client = useQueryClient();
  const add = useMutation({
    mutationFn: () => post("/users", { name, password }),
    onSuccess: () => {
      setName("");
      setPassword("");
      client.invalidateQueries({ queryKey: ["settings"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };
  return (
    <form onSubmit={submit} className="mt-4 border-t border-line pt-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="Name"><input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} className={inputClass} /></Field>
        <Field label="Temporary password"><input required minLength={8} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} /></Field>
        <Button type="submit" busy={add.isPending}><UserPlus className="size-4" /> Add</Button>
      </div>
      <div className="mt-2"><ErrorNote error={add.error} /></div>
    </form>
  );
}

export default function Settings() {
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: () => get<Data>("/settings") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => get<{ name: string }>("/me") }).data?.name;
  if (isLoading) return <Loading />;
  if (!data) return <ErrorNote error={error} />;
  if (!data.notifications || !data.trackers) {
    return (
      <div>
        <PageHeader eyebrow="Settings" title="Connections and people" />
        <Card className="flex items-start gap-3 p-5">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-gold" />
          <div className="text-sm leading-relaxed">
            <p className="font-semibold">The backend needs a restart</p>
            <p className="text-ink-2">This page was updated, but the server is still running older code. Stop the backend, start it again, then reload this page. Your data is safe.</p>
          </div>
        </Card>
      </div>
    );
  }
  return (
    <div>
      <PageHeader eyebrow="Settings" title="Connections and people" />
      <section className="mb-9">
        <SectionTitle aside="Checked just now against the live services">Connections</SectionTitle>
        <GitHubApp settings={data} />
        <div className="grid gap-4 lg:grid-cols-2">
          <Connection title="Claude" ok={data.anthropic.ok} problem={data.anthropic.problem} detail={`Connected. Agents use ${data.model}.`} field="anthropic_key" label="New API key" placeholder="sk-ant-..." />
          <Connection title="GitHub" ok={data.github.ok} problem={data.github.problem} detail={`Connected as ${data.github.login}.`} field="github_token" label={data.github.mode === "app" ? "Personal token (the app takes priority)" : "New token"} placeholder="github_pat_..." />
        </div>
      </section>
      <Notifications settings={data} />
      <Trackers settings={data} />
      <Workers settings={data} />
      <ChangePassword />
      <section>
        <SectionTitle>Approvers</SectionTitle>
        <Card className="p-5">
          <ul className="flex flex-wrap gap-2">
            {data.users.map((u) => (
              <li key={u.name} className="flex items-center gap-2 rounded-full bg-sunken py-1 pr-2.5 pl-1 text-sm font-medium">
                <span className="flex size-6 items-center justify-center rounded-full bg-ink text-xs font-bold text-paper">{u.name[0].toUpperCase()}</span>
                {u.name}
                {u.name === me ? <span className="text-xs font-normal text-ink-3">you</span> : <RemoveApprover name={u.name} />}
              </li>
            ))}
          </ul>
          <AddApprover />
        </Card>
      </section>
    </div>
  );
}
