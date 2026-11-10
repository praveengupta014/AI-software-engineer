import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, Lock } from "lucide-react";
import { useRef, useState } from "react";
import { get, type Repo } from "../lib/api";
import { cx, inputClass } from "./ui";

/** Searchable list of the repositories the connected GitHub token can push to. */
export function RepoPicker({ value, onChange }: { value: string; onChange: (repo: string, defaultBranch?: string) => void }) {
  const [open, setOpen] = useState(false);
  const closing = useRef<number>(undefined);
  const repos = useQuery({ queryKey: ["github-repos"], queryFn: () => get<Repo[]>("/github/repos"), staleTime: 60_000 });
  const needle = value.toLowerCase();
  const matches = (repos.data ?? []).filter((r) => r.full_name.toLowerCase().includes(needle)).slice(0, 8);

  return (
    <div className="relative">
      <input
        required
        role="combobox"
        aria-expanded={open}
        aria-label="Repository"
        aria-autocomplete="list"
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder="Search your repositories"
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => { closing.current = window.setTimeout(() => setOpen(false), 120); }}
        className={cx(inputClass, "pr-9 font-mono")}
      />
      <ChevronsUpDown className="pointer-events-none absolute top-2.5 right-3 size-4 text-ink-3" />
      {open && (
        <div role="listbox" className="absolute z-20 mt-1.5 w-full overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
          {repos.isLoading && <p className="px-3 py-2.5 text-sm text-ink-3">Loading your repositories</p>}
          {repos.error && <p className="px-3 py-2.5 text-sm text-clay">{(repos.error as Error).message}. You can still type owner/name.</p>}
          {repos.data && matches.length === 0 && <p className="px-3 py-2.5 text-sm text-ink-3">No repository matches. You can still type owner/name.</p>}
          {matches.map((repo) => (
            <button
              key={repo.full_name}
              type="button"
              role="option"
              aria-selected={repo.full_name === value}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { onChange(repo.full_name, repo.default_branch); setOpen(false); }}
              className="block w-full px-3 py-2 text-left transition-colors hover:bg-gold-soft/50"
            >
              <span className="flex items-center gap-1.5 font-mono text-[13px] font-medium">
                {repo.full_name} {repo.private && <Lock className="size-3 text-ink-3" />}
              </span>
              {repo.description && <span className="line-clamp-1 text-xs text-ink-3">{repo.description}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
