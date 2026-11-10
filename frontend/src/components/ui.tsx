import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");
export { cx };

type Tone = "neutral" | "moss" | "gold" | "clay" | "ocean";

const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2",
  moss: "bg-moss-soft text-moss",
  gold: "bg-gold-soft text-gold",
  clay: "bg-clay-soft text-clay",
  ocean: "bg-ocean-soft text-ocean",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap", TONES[tone])}>
      {children}
    </span>
  );
}

const STATUS: Record<string, { tone: Tone; label: string }> = {
  pending: { tone: "gold", label: "Awaiting you" },
  approved: { tone: "moss", label: "Approved" },
  executed: { tone: "moss", label: "Done" },
  failed: { tone: "clay", label: "Failed" },
  rejected: { tone: "clay", label: "Rejected" },
  changes_requested: { tone: "ocean", label: "Sent back" },
  planning: { tone: "ocean", label: "Planning" },
  in_progress: { tone: "ocean", label: "In progress" },
  done: { tone: "moss", label: "Done" },
  running: { tone: "ocean", label: "Working" },
  queued: { tone: "neutral", label: "Queued" },
};

export function StatusBadge({ status }: { status: string }) {
  const entry = STATUS[status] ?? { tone: "neutral" as Tone, label: status };
  return <Badge tone={entry.tone}>{entry.label}</Badge>;
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "approve" | "ghost" | "danger";
  busy?: boolean;
};

const VARIANTS = {
  primary: "bg-ink text-paper shadow-sm hover:-translate-y-px hover:shadow-md",
  approve: "bg-moss text-white shadow-sm hover:-translate-y-px hover:bg-moss/95 hover:shadow-md",
  ghost: "border border-line-strong bg-surface text-ink hover:bg-sunken",
  danger: "border border-clay/40 bg-surface text-clay hover:bg-clay-soft",
};

export function Button({ variant = "ghost", busy, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition-all active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
        VARIANTS[variant],
        className,
      )}
    >
      {busy && <LoaderCircle className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-2xl border border-line bg-surface shadow-card", className)}>{children}</div>;
}

export function PageHeader({ eyebrow, title, children }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-sm text-ink-3">{eyebrow}</div>}
        <h1 className="font-serif text-[2.1rem] leading-tight font-medium tracking-tight text-balance">{title}</h1>
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </header>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-semibold text-ink">{children}</h2>
      {aside && <div className="text-xs text-ink-3">{aside}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong px-6 py-12 text-center">
      <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-sunken text-ink-3">{icon}</div>
      <p className="font-serif text-xl">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">
      {error instanceof Error ? error.message : "Something went wrong"}
    </p>
  );
}

export function Loading() {
  return (
    <div className="flex items-center gap-2 py-16 text-sm text-ink-3">
      <LoaderCircle className="size-4 animate-spin" /> Loading
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-ink focus:outline-none";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}
