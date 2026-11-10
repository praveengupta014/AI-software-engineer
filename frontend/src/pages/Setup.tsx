import { ArrowLeft, ArrowRight, Check, ExternalLink, ShieldCheck } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { Button, ErrorNote, Field, cx, inputClass } from "../components/ui";
import { ApiError, post, setToken, type Health } from "../lib/api";

type Step = "account" | "claude" | "github";

const LABEL: Record<Step, string> = { account: "Your account", claude: "Claude", github: "GitHub" };

function Guide({ href, linkText, children }: { href: string; linkText: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-sunken/70 p-3.5 text-sm leading-relaxed text-ink-2">
      {children}
      <a href={href} target="_blank" rel="noreferrer" className="mt-1.5 flex items-center gap-1 font-semibold text-ocean hover:underline">
        {linkText} <ExternalLink className="size-3.5" />
      </a>
    </div>
  );
}

export default function Setup({ needs }: { needs: Health["needs"] }) {
  const steps: Step[] = ["account", ...(needs.anthropic_key ? (["claude"] as const) : []), ...(needs.github_token ? (["github"] as const) : [])];
  const [index, setIndex] = useState(0);
  const [form, setForm] = useState({ name: "", password: "", anthropic_key: "", github_token: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const step = steps[index];
  const last = index === steps.length - 1;
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!last) return setIndex(index + 1);
    setBusy(true);
    try {
      const { token } = await post<{ token: string }>("/setup", form);
      setToken(token);
      window.location.assign("/");
    } catch (failure) {
      setBusy(false);
      setError(failure);
      const message = failure instanceof ApiError ? failure.message : "";
      const back = /github/i.test(message) ? "github" : /anthropic|claude|model/i.test(message) ? "claude" : null;
      if (back && steps.includes(back)) setIndex(steps.indexOf(back));
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-ink p-5 text-ink">
      <div className="aurora" />
      <div className="dot-grid absolute inset-0" />
      <div className="relative w-full max-w-lg">
        <div className="mb-6 flex items-center justify-center gap-2.5 text-paper">
          <img src="/favicon.svg" alt="" className="size-8 rounded-md ring-1 ring-white/15" />
          <span className="font-serif text-2xl font-medium">Countersign</span>
        </div>
        <motion.form layout onSubmit={submit} className="rounded-3xl bg-surface p-7 shadow-2xl sm:p-8">
          <ol className="mb-7 flex items-center gap-2">
            {steps.map((s, i) => (
              <li key={s} className="flex flex-1 items-center gap-2 text-xs font-semibold">
                <span className={cx("flex size-6 shrink-0 items-center justify-center rounded-full transition-colors", i < index ? "bg-moss text-white" : i === index ? "bg-ink text-paper" : "bg-sunken text-ink-3")}>
                  {i < index ? <Check className="size-3.5" /> : i + 1}
                </span>
                <span className={cx("truncate max-sm:hidden", i === index ? "text-ink" : "text-ink-3")}>{LABEL[s]}</span>
              </li>
            ))}
          </ol>

          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={step} initial={{ opacity: 0, x: 18 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -18 }} transition={{ duration: 0.18 }} className="space-y-4">
              {step === "account" && (
                <>
                  <div>
                    <h1 className="font-serif text-3xl font-medium">Create your account</h1>
                    <p className="mt-1 text-sm text-ink-2">This name goes on every approval you sign.</p>
                  </div>
                  <Field label="Your name">
                    <input required minLength={2} autoFocus autoComplete="name" value={form.name} onChange={set("name")} className={inputClass} />
                  </Field>
                  <Field label="Password" hint="At least 8 characters">
                    <input required minLength={8} type="password" autoComplete="new-password" value={form.password} onChange={set("password")} className={inputClass} />
                  </Field>
                </>
              )}
              {step === "claude" && (
                <>
                  <div>
                    <h1 className="font-serif text-3xl font-medium">Connect Claude</h1>
                    <p className="mt-1 text-sm text-ink-2">This is what powers the agents. Usage is billed to your Anthropic account.</p>
                  </div>
                  <Guide href="https://console.anthropic.com/settings/keys" linkText="Create an API key">
                    Open the Anthropic Console, choose <strong className="font-semibold text-ink">Create Key</strong> and paste it below.
                  </Guide>
                  <Field label="Claude API key">
                    <input required autoFocus type="password" autoComplete="off" spellCheck={false} placeholder="sk-ant-..." value={form.anthropic_key} onChange={set("anthropic_key")} className={cx(inputClass, "font-mono")} />
                  </Field>
                </>
              )}
              {step === "github" && (
                <>
                  <div>
                    <h1 className="font-serif text-3xl font-medium">Connect GitHub</h1>
                    <p className="mt-1 text-sm text-ink-2">Agents read through this token. Writes happen only after you approve them.</p>
                  </div>
                  <Guide href="https://github.com/settings/personal-access-tokens/new" linkText="Create a fine-grained token">
                    Pick the repositories Countersign may use, then give it <strong className="font-semibold text-ink">Contents</strong> and <strong className="font-semibold text-ink">Pull requests</strong>, both read and write.
                  </Guide>
                  <Field label="GitHub token">
                    <input required autoFocus type="password" autoComplete="off" spellCheck={false} placeholder="github_pat_..." value={form.github_token} onChange={set("github_token")} className={cx(inputClass, "font-mono")} />
                  </Field>
                </>
              )}
            </motion.div>
          </AnimatePresence>

          {(step === "claude" || step === "github") && (
            <p className="mt-3 flex items-start gap-1.5 text-xs text-ink-3">
              <ShieldCheck className="mt-px size-3.5 shrink-0" /> Stored on your server only and never sent back to the browser.
            </p>
          )}
          <div className="mt-4"><ErrorNote error={error} /></div>
          <div className="mt-5 flex gap-2">
            {index > 0 && <Button type="button" onClick={() => setIndex(index - 1)} aria-label="Back"><ArrowLeft className="size-4" /></Button>}
            <Button type="submit" variant="primary" busy={busy} className="flex-1">
              {busy ? "Checking your connections" : last ? "Finish setup" : <>Continue <ArrowRight className="size-4" /></>}
            </Button>
          </div>
        </motion.form>
      </div>
    </div>
  );
}
