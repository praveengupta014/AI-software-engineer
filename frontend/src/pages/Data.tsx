import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Copy, Database, FolderOpen, Check, Lock, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { Button, Card, EmptyState, ErrorNote, Loading, PageHeader, StatusBadge, cx, inputClass } from "../components/ui";
import { get, type DataPage, type DataSummary, type Payload } from "../lib/api";
import { fullTime } from "../lib/format";

const titleCase = (name: string) => {
  const words = name.replace(/_/g, " ");
  return words[0].toUpperCase() + words.slice(1);
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value);
}

function Cell({ column, value }: { column: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return <span className="text-ink-3">—</span>;
  if ((column === "status" || column === "state") && typeof value === "string") return <StatusBadge status={value} />;
  if (isTimestamp(value)) return <span className="whitespace-nowrap text-ink-2">{fullTime(value)}</span>;
  if (typeof value === "object") return <code className="font-mono text-xs text-ink-2">{JSON.stringify(value).slice(0, 60)}</code>;
  const text = String(value);
  const mono = /(^|_)(id|hash|repo|model)$/.test(column) || column === "seq";
  return <span className={cx("block max-w-72 truncate", mono && "font-mono text-xs")} title={text}>{text}</span>;
}

function DetailValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <span className="text-ink-3">Empty</span>;
  if (isTimestamp(value)) return <>{fullTime(value)}</>;
  if (typeof value === "object") {
    return <pre className="max-h-96 overflow-auto rounded-lg bg-sunken p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{JSON.stringify(value, null, 2)}</pre>;
  }
  return <span className="break-words whitespace-pre-wrap">{String(value)}</span>;
}

function RowDrawer({ table, rowId, onClose }: { table: string; rowId: string; onClose: () => void }) {
  const row = useQuery({ queryKey: ["data-row", table, rowId], queryFn: () => get<Payload>(`/data/${table}/${rowId}`) });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="fixed inset-0 z-30 bg-ink/40" />
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label="Row details"
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", stiffness: 380, damping: 38 }}
        className="fixed inset-y-0 right-0 z-40 flex w-full max-w-xl flex-col bg-surface shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-serif text-xl font-medium">Row details</h2>
          <button aria-label="Close" autoFocus onClick={onClose} className="rounded-md p-1.5 text-ink-3 hover:bg-sunken"><X className="size-4" /></button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">
          {row.isLoading && <Loading />}
          <ErrorNote error={row.error} />
          {row.data && (
            <dl className="space-y-4">
              {Object.entries(row.data).map(([key, value]) => (
                <div key={key}>
                  <dt className="mb-0.5 text-xs font-semibold text-ink-3">{titleCase(key)}</dt>
                  <dd className="text-sm"><DetailValue value={value} /></dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </motion.aside>
    </>
  );
}

function Storage({ kind, path, size }: { kind: string; path: string; size: number }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(path);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Card className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
      <FolderOpen className="size-5 shrink-0 text-gold" />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-ink-3">{kind === "postgresql" ? "PostgreSQL database" : "Saved on this computer"} · {formatBytes(size)}</p>
        <code className="block truncate font-mono text-[13px]" title={path}>{path}</code>
      </div>
      <Button onClick={copy} className="!px-2.5 !py-1.5 !text-xs">
        {copied ? <Check className="size-3.5 text-moss" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy path"}
      </Button>
    </Card>
  );
}

export default function Data() {
  const [table, setTable] = useState("requirements");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [openRow, setOpenRow] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  const summary = useQuery({ queryKey: ["data-summary"], queryFn: () => get<DataSummary>("/data"), refetchInterval: 5000 });
  const rows = useQuery({
    queryKey: ["data-rows", table, query, page],
    queryFn: () => get<DataPage>(`/data/${table}?${new URLSearchParams({ q: query, page: String(page) })}`),
    placeholderData: keepPreviousData,
    refetchInterval: 5000,
  });

  const choose = (key: string) => {
    setTable(key);
    setSearch("");
    setQuery("");
    setPage(1);
  };

  const data = rows.data;
  const lastPage = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const firstShown = data && data.total ? (data.page - 1) * data.page_size + 1 : 0;
  const lastShown = data ? Math.min(data.total, data.page * data.page_size) : 0;
  const label = summary.data?.tables.find((t) => t.key === table)?.label ?? "";

  return (
    <div>
      <PageHeader eyebrow="Data" title="Everything Countersign has saved" />
      <p className="-mt-3 mb-6 flex items-center gap-1.5 text-[15px] text-ink-2">
        <Lock className="size-4 shrink-0 text-ink-3" /> View only. Passwords, keys and tokens are never shown here.
      </p>

      {summary.data && <Storage kind={summary.data.storage.kind} path={summary.data.storage.path} size={summary.data.storage.size_bytes} />}
      <ErrorNote error={summary.error} />

      <div role="tablist" aria-label="Tables" className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {summary.data?.tables.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={t.key === table}
            onClick={() => choose(t.key)}
            className={cx(
              "rounded-xl border px-3.5 py-3 text-left transition-all hover:-translate-y-0.5",
              t.key === table ? "border-ink bg-ink text-paper shadow-card" : "border-line bg-surface hover:border-line-strong",
            )}
          >
            <span className="block font-serif text-2xl leading-tight tabular-nums">{t.count}</span>
            <span className={cx("block text-[13px]", t.key === table ? "text-paper/70" : "text-ink-2")}>{t.label}</span>
          </button>
        ))}
      </div>

      <div className="relative mb-3 max-w-md">
        <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-ink-3" />
        <input
          type="search"
          aria-label={`Search ${label}`}
          placeholder={`Search ${label.toLowerCase()}`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={cx(inputClass, "pl-9")}
        />
      </div>

      <ErrorNote error={rows.error} />
      {rows.isLoading ? <Loading /> : data && data.rows.length === 0 ? (
        <EmptyState icon={<Database className="size-5" />} title={query ? "Nothing matches that search" : `No ${label.toLowerCase()} yet`} />
      ) : data && (
        <Card className="overflow-hidden">
          <div className="relative overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="text-xs text-ink-3">
                  {data.columns.map((c) => <th key={c} scope="col" className="px-4 py-2.5 font-semibold whitespace-nowrap">{titleCase(c)}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => {
                  const id = String(row[data.primary_key]);
                  return (
                    <tr
                      key={id}
                      tabIndex={0}
                      aria-label={`Open row ${id}`}
                      onClick={() => setOpenRow(id)}
                      onKeyDown={(e) => { if (e.key === "Enter") setOpenRow(id); }}
                      className="cursor-pointer border-t border-line transition-colors hover:bg-gold-soft/30"
                    >
                      {data.columns.map((c) => <td key={c} className="px-4 py-2.5"><Cell column={c} value={row[c]} /></td>)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5 text-[13px] text-ink-2">
            <span className="tabular-nums">{firstShown}–{lastShown} of {data.total}</span>
            <span className="flex items-center gap-1.5">
              <Button aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)} className="!p-1.5"><ChevronLeft className="size-4" /></Button>
              <span className="tabular-nums">Page {page} of {lastPage}</span>
              <Button aria-label="Next page" disabled={page >= lastPage} onClick={() => setPage(page + 1)} className="!p-1.5"><ChevronRight className="size-4" /></Button>
            </span>
          </div>
        </Card>
      )}

      <AnimatePresence>
        {openRow && <RowDrawer key="drawer" table={table} rowId={openRow} onClose={() => setOpenRow(null)} />}
      </AnimatePresence>
    </div>
  );
}
