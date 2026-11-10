import { motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Button, ErrorNote, Field, inputClass } from "../components/ui";
import { post, setToken } from "../lib/api";

export default function Login() {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await post<{ token: string }>("/auth/login", { name, password });
      setToken(token);
      window.location.assign("/");
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="relative flex flex-col justify-between overflow-hidden bg-ink p-10 text-paper lg:p-14">
        <div className="aurora" />
        <div className="dot-grid absolute inset-0" />
        <Link to="/welcome" className="relative flex items-center gap-2.5">
          <img src="/favicon.svg" alt="" className="size-8 rounded-md ring-1 ring-white/15" />
          <span className="font-serif text-2xl font-medium">Countersign</span>
        </Link>
        <h1 className="relative my-16 max-w-lg font-serif text-5xl leading-[1.08] font-medium tracking-tight text-balance">
          Your agents have been waiting for a signature.
        </h1>
        <p className="relative font-mono text-xs text-paper/50">Every decision is recorded under your name.</p>
      </section>
      <section className="flex items-center justify-center p-8">
        <motion.form initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} onSubmit={submit} className="w-full max-w-sm space-y-5">
          <div>
            <h2 className="font-serif text-3xl font-medium">Sign in</h2>
            <p className="mt-1 text-sm text-ink-2">Passwords are case-sensitive, and spaces count.</p>
          </div>
          <Field label="Account name" hint="The name you chose during setup, not your email">
            <input required autoFocus autoComplete="username" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </Field>
          <Field label="Password">
            <input required type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
          </Field>
          <ErrorNote error={error} />
          <Button type="submit" variant="primary" busy={busy} className="w-full">Sign in</Button>
        </motion.form>
      </section>
    </div>
  );
}
