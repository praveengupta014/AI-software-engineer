import {
  ArrowRight, Bot, ClipboardList, Code2, Eye, FileCheck2, FingerprintPattern, FlaskConical,
  GitPullRequest, Link2, MessageSquareText, PenLine, RotateCcw, ShieldAlert, ShieldCheck, Unlink2,
} from "lucide-react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll, useTransform } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { cx } from "../components/ui";
import { getToken } from "../lib/api";

const ease = [0.2, 0.7, 0.2, 1] as const;

function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 26 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-70px" }}
      transition={{ duration: 0.65, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

function Cta({ configured, large }: { configured: boolean; large?: boolean }) {
  const signedIn = !!getToken();
  const to = signedIn ? "/" : configured ? "/login" : "/setup";
  const label = signedIn ? "Open Countersign" : configured ? "Sign in" : "Get started";
  return (
    <motion.span className="inline-block" whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}>
      <Link
        to={to}
        reloadDocument
        className={cx(
          "inline-flex items-center gap-2 rounded-xl bg-gold-bright font-bold text-ink shadow-[0_8px_30px_-8px_rgb(232_176_74/0.65)]",
          large ? "px-6 py-3.5 text-base" : "px-4 py-2 text-sm",
        )}
      >
        {label} <ArrowRight className="size-4" />
      </Link>
    </motion.span>
  );
}

const HEADLINE = "AI engineers that ask before they act.".split(" ");

const DIFF = [
  { sign: "+", text: "class RateLimiter:" },
  { sign: "+", text: "    def allow(self, key):" },
  { sign: "+", text: "        hits = self._window(key)" },
  { sign: "+", text: "        return len(hits) < self.limit" },
];

const SCENE_STEPS = ["Reading the repository", "Writing the change", "Running risk checks", "Waiting for you", "Signed and recorded"];

/** Illustration of a proposal moving through the gate. It loops; nothing here is live data. */
function ProductScene() {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setPhase((p) => (p + 1) % 5), 1900);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="relative rounded-3xl border border-white/12 bg-white/[0.06] p-2 shadow-2xl backdrop-blur-xl">
      <div className="overflow-hidden rounded-[1.25rem] bg-surface text-ink">
        <div className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-ocean-soft text-ocean"><Bot className="size-[18px]" /></span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Code: add a rate limiter</p>
            <AnimatePresence mode="wait">
              <motion.p key={phase} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} className="text-xs text-ink-3">
                {SCENE_STEPS[phase]}
              </motion.p>
            </AnimatePresence>
          </div>
          <span className="flex gap-1">
            {SCENE_STEPS.map((step, i) => (
              <span key={step} className={cx("h-1.5 w-4 rounded-full transition-colors duration-500", i <= phase ? "bg-moss" : "bg-sunken")} />
            ))}
          </span>
        </div>
        <div className="relative h-52 bg-[#fbf9f3] font-mono text-[12.5px] leading-7">
          <div className="border-b border-line/70 px-5 py-1.5 text-[11.5px] text-ink-3">app/rate_limit.py</div>
          {DIFF.map((line, i) => (
            <motion.div
              key={line.text}
              animate={{ opacity: phase >= 1 ? 1 : 0.12, x: phase >= 1 ? 0 : -6 }}
              transition={{ delay: phase === 1 ? i * 0.16 : 0, duration: 0.3 }}
              className="flex gap-3 whitespace-pre bg-moss-soft/60 px-5"
            >
              <span className="text-moss">{line.sign}</span>{line.text}
            </motion.div>
          ))}
          <AnimatePresence>
            {phase >= 2 && (
              <motion.div key="risk" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="absolute bottom-3 left-5 flex items-center gap-1.5 rounded-full bg-moss-soft px-2.5 py-1 font-sans text-xs font-semibold text-moss">
                <ShieldCheck className="size-3.5" /> No risks flagged
              </motion.div>
            )}
            {phase >= 3 && (
              <motion.div
                key="stamp"
                initial={{ opacity: 0, scale: 2, rotate: -14 }}
                animate={{ opacity: phase === 3 ? 0.28 : 1, scale: phase === 3 ? 1.04 : 1, rotate: -6 }}
                exit={{ opacity: 0 }}
                transition={{ type: "spring", stiffness: 480, damping: 20 }}
                className="absolute right-5 bottom-4 rounded-md border-[2.5px] border-moss px-3 py-1.5 font-sans text-moss"
              >
                <div className="text-sm font-extrabold tracking-[0.14em]">APPROVED</div>
                <div className="font-mono text-[10px]">by you</div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="flex items-center gap-2 border-t border-line px-5 py-2.5 font-mono text-[11px] text-ink-3">
          <Link2 className="size-3.5" />
          <span className="truncate">
            ledger
            <motion.span animate={{ color: phase === 4 ? "#2c6a4e" : "#827c70" }}> · 8f3a…c1 → 2bd9…07{phase === 4 ? " → a41e…5d" : ""}</motion.span>
          </span>
        </div>
      </div>
    </div>
  );
}

const STAGES = [
  { icon: ClipboardList, name: "Plan", agent: "Planner", text: "Reads your repository and turns a requirement into small tasks, each with acceptance criteria. Anything unclear comes back as a question." },
  { icon: Code2, name: "Code", agent: "Coder", text: "Implements one task, matching the conventions it finds. You see a real diff, and can edit it before you sign." },
  { icon: FlaskConical, name: "Tests", agent: "Tester", text: "Writes tests against the approved change, one for each acceptance criterion, in your existing framework." },
  { icon: GitPullRequest, name: "Pull request", agent: "You", text: "Countersign assembles only what you approved. The branch and PR are created at the moment you say so, and not before." },
  { icon: MessageSquareText, name: "Review", agent: "Reviewer", text: "Reads the PR and drafts comments. You choose what gets posted. The AI never formally approves its own work." },
];

function Pipeline() {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const [active, setActive] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (value) => setActive(Math.min(STAGES.length - 1, Math.floor(value * STAGES.length))));
  const lineHeight = useTransform(scrollYProgress, [0, 1], ["0%", "100%"]);
  const stage = STAGES[active];
  const Icon = stage.icon;

  return (
    <section id="how" ref={ref} className="relative h-[320vh] bg-paper text-ink">
      <div className="sticky top-0 flex min-h-dvh items-center">
        <div className="mx-auto grid w-full max-w-6xl gap-10 px-6 lg:grid-cols-[1fr_1.1fr] lg:gap-20">
          <div className="relative pl-7">
            <div className="absolute top-2 bottom-2 left-[5px] w-0.5 bg-line" />
            <motion.div style={{ height: lineHeight }} className="absolute top-2 left-[5px] w-0.5 bg-moss" />
            <p className="mb-5 text-sm font-semibold text-moss">How it works</p>
            <ol className="space-y-1">
              {STAGES.map((s, i) => (
                <li key={s.name} className="relative">
                  <span className={cx("absolute top-[1.15rem] -left-[26px] size-2.5 rounded-full transition-colors duration-300", i <= active ? "bg-moss" : "bg-line-strong")} />
                  <p className={cx("py-1.5 font-serif text-[2.2rem] leading-tight font-medium tracking-tight transition-colors duration-300 sm:text-5xl", i === active ? "text-ink" : "text-ink/20")}>
                    {s.name}
                  </p>
                </li>
              ))}
            </ol>
          </div>
          <div className="flex items-center">
            <AnimatePresence mode="wait">
              <motion.div
                key={stage.name}
                initial={{ opacity: 0, y: 22 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -14 }}
                transition={{ duration: 0.28, ease }}
                className="w-full rounded-3xl border border-line bg-surface p-7 shadow-card sm:p-9"
              >
                <span className="flex size-12 items-center justify-center rounded-2xl bg-ink text-gold-bright"><Icon className="size-6" /></span>
                <p className="mt-6 text-sm font-semibold text-ink-3">Step {active + 1} of {STAGES.length} · {stage.agent}</p>
                <p className="mt-2 text-xl leading-relaxed">{stage.text}</p>
                <div className="mt-6 inline-flex items-center gap-2 rounded-full bg-gold-soft px-3 py-1.5 text-sm font-semibold text-gold">
                  <PenLine className="size-4" /> Stops here for your signature
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}

const FEATURES = [
  { icon: Eye, title: "Agents can only read", text: "An agent has no tool that changes your repository. All it can do is hand back a proposal.", span: "lg:col-span-2" },
  { icon: FingerprintPattern, title: "You sign the exact content", text: "An approval is tied to a hash of what you saw. If it changed, the approval fails.", span: "" },
  { icon: ShieldAlert, title: "Risks are flagged by code", text: "CI changes, likely secrets and dependency edits are caught by plain code that a prompt injection cannot argue with.", span: "" },
  { icon: FileCheck2, title: "You stay the editor", text: "Change the code, rewrite a comment or send it back with a note. Every revision is kept, with who made it and when.", span: "lg:col-span-2" },
];

function Features() {
  return (
    <section id="control" className="bg-paper px-6 pb-28 text-ink">
      <div className="mx-auto max-w-6xl">
        <Reveal>
          <h2 className="max-w-2xl font-serif text-4xl leading-tight font-medium tracking-tight sm:text-5xl">Autonomy where it helps. A person where it counts.</h2>
        </Reveal>
        <div className="mt-11 grid gap-4 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text, span }, i) => (
            <Reveal key={title} delay={i * 0.07} className={span}>
              <motion.article whileHover={{ y: -5 }} className="h-full rounded-3xl border border-line bg-surface p-7 shadow-card">
                <span className="flex size-10 items-center justify-center rounded-xl bg-moss-soft text-moss"><Icon className="size-5" /></span>
                <h3 className="mt-5 text-lg font-bold">{title}</h3>
                <p className="mt-1.5 leading-relaxed text-ink-2">{text}</p>
              </motion.article>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

const LEDGER = [
  { who: "Planner", what: "Proposed a plan", hash: "8f3a91c1" },
  { who: "Asha", what: "Approved the plan", hash: "2bd9e407" },
  { who: "Coder", what: "Read app/main.py", hash: "a41e0c5d" },
  { who: "Coder", what: "Proposed a change", hash: "c07b62fa" },
  { who: "Asha", what: "Edited and approved", hash: "5e18d3b9" },
  { who: "Countersign", what: "Opened a pull request", hash: "e96f27a4" },
];

/** Hands-on demonstration of the idea behind the audit chain. Runs entirely in the page. */
function ChainDemo() {
  const [tampered, setTampered] = useState<number | null>(null);
  return (
    <section id="audit" className="relative overflow-hidden bg-ink px-6 py-28 text-paper">
      <div className="dot-grid absolute inset-0" />
      <div className="relative mx-auto max-w-6xl">
        <Reveal className="max-w-2xl">
          <p className="mb-3 text-sm font-semibold text-gold-bright">The audit trail</p>
          <h2 className="font-serif text-4xl leading-tight font-medium tracking-tight sm:text-5xl">A ledger that shows when someone touches it.</h2>
          <p className="mt-4 text-lg leading-relaxed text-paper/65">Each entry is sealed to the one before it. Try it: click any entry below to alter it, and watch everything after it fail.</p>
        </Reveal>
        <div className="mt-11 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {LEDGER.map((entry, i) => {
            const broken = tampered !== null && i >= tampered;
            return (
              <Reveal key={entry.hash} delay={i * 0.05}>
                <motion.button
                  type="button"
                  aria-label={`Tamper with entry ${i + 1}: ${entry.what}`}
                  onClick={() => setTampered(i)}
                  whileHover={{ y: -3 }}
                  animate={{
                    backgroundColor: broken ? "rgba(178,63,43,0.22)" : "rgba(255,255,255,0.05)",
                    borderColor: broken ? "rgba(230,120,100,0.7)" : "rgba(255,255,255,0.12)",
                    x: tampered === i ? [0, -6, 6, -4, 4, 0] : 0,
                  }}
                  transition={{ delay: tampered !== null && i > tampered ? (i - tampered) * 0.11 : 0, duration: 0.35 }}
                  className="w-full rounded-2xl border p-4 text-left"
                >
                  <span className="flex items-center justify-between gap-2 font-mono text-xs text-paper/50">
                    <span>#{i + 1}</span>
                    {broken ? <Unlink2 className="size-3.5 text-[#f0a090]" /> : <Link2 className="size-3.5" />}
                  </span>
                  <span className="mt-2 block font-semibold">{tampered === i ? "Entry altered" : entry.what}</span>
                  <span className="mt-0.5 flex items-center justify-between gap-2 text-sm text-paper/55">
                    {entry.who}
                    <code className={cx("font-mono text-xs", broken && "text-[#f0a090] line-through")}>{entry.hash}</code>
                  </span>
                </motion.button>
              </Reveal>
            );
          })}
        </div>
        <div className="mt-6 flex min-h-11 flex-wrap items-center gap-3" aria-live="polite">
          {tampered === null ? (
            <p className="flex items-center gap-2 text-sm font-semibold text-[#8fd0ae]"><ShieldCheck className="size-4" /> Chain intact. All {LEDGER.length} entries verified.</p>
          ) : (
            <>
              <p className="flex items-center gap-2 text-sm font-semibold text-[#f0a090]"><ShieldAlert className="size-4" /> Tampering detected at entry {tampered + 1}.</p>
              <button onClick={() => setTampered(null)} className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-sm font-semibold hover:bg-white/15">
                <RotateCcw className="size-3.5" /> Reset
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

export default function Landing({ configured }: { configured: boolean }) {
  const { scrollY } = useScroll();
  const sceneY = useTransform(scrollY, [0, 600], [0, -60]);
  const glow = useTransform(scrollY, [0, 500], [1, 0.3]);

  return (
    <div className="overflow-x-clip bg-ink text-paper">
      <header className="fixed inset-x-0 top-0 z-30 border-b border-white/8 bg-ink/92 backdrop-blur-lg">
        <div className="mx-auto flex max-w-6xl items-center gap-7 px-6 py-3">
          <span className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-7 rounded-md ring-1 ring-white/15" />
            <span className="font-serif text-xl font-medium">Countersign</span>
          </span>
          <nav className="flex gap-6 text-sm font-medium text-paper/65 max-md:hidden">
            <a href="#how" className="transition-colors hover:text-white">How it works</a>
            <a href="#control" className="transition-colors hover:text-white">Control</a>
            <a href="#audit" className="transition-colors hover:text-white">Audit trail</a>
          </nav>
          <div className="ml-auto"><Cta configured={configured} /></div>
        </div>
      </header>

      <section className="relative flex min-h-dvh items-center overflow-hidden px-6 pt-28 pb-20">
        <motion.div style={{ opacity: glow }} className="aurora" />
        <div className="dot-grid absolute inset-0" />
        <div className="relative mx-auto grid w-full max-w-6xl items-center gap-14 lg:grid-cols-[1.05fr_1fr]">
          <div>
            <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/6 px-3 py-1 text-[13px] font-medium text-paper/80">
              <span className="size-1.5 rounded-full bg-gold-bright" /> A software team of AI agents, with you in charge
            </motion.p>
            <h1 className="font-serif text-[3.2rem] leading-[1.03] font-medium tracking-tight sm:text-7xl">
              {HEADLINE.map((word, i) => (
                <motion.span
                  key={word}
                  initial={{ opacity: 0, y: 26, filter: "blur(8px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  transition={{ duration: 0.6, delay: 0.1 + i * 0.07, ease }}
                  className={cx("mr-[0.24em] inline-block", word === "ask" && "text-gold-bright italic")}
                >
                  {word}
                </motion.span>
              ))}
            </h1>
            <motion.p initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.65, duration: 0.6 }} className="mt-6 max-w-lg text-lg leading-relaxed text-paper/68">
              Countersign plans your requirements, writes code and tests, and reviews pull requests. Nothing reaches your repository without your signature, and every step is on the record.
            </motion.p>
            <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.8, duration: 0.6 }} className="mt-8 flex flex-wrap items-center gap-5">
              <Cta configured={configured} large />
              <a href="#how" className="text-sm font-semibold text-paper/70 transition-colors hover:text-white">See how it works</a>
            </motion.div>
          </div>
          <motion.div style={{ y: sceneY }} initial={{ opacity: 0, y: 40, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.35, duration: 0.8, ease }}>
            <ProductScene />
          </motion.div>
        </div>
      </section>

      <Pipeline />
      <Features />
      <ChainDemo />

      <section className="relative overflow-hidden border-t border-white/8 px-6 py-28 text-center">
        <div className="aurora" />
        <Reveal className="relative mx-auto max-w-2xl">
          <h2 className="font-serif text-4xl leading-tight font-medium tracking-tight sm:text-6xl">Hire the agents. Keep the pen.</h2>
          <p className="mt-4 mb-8 text-lg text-paper/65">Connect Claude and GitHub, and file your first requirement in minutes.</p>
          <Cta configured={configured} large />
        </Reveal>
      </section>

      <footer className="border-t border-white/8 px-6 py-6 text-center text-sm text-paper/40">Countersign</footer>
    </div>
  );
}
