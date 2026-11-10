import { FileMinus2, FilePen, FilePlus2 } from "lucide-react";
import type { FileChange } from "../lib/api";
import { cx } from "./ui";

const ICON = { create: FilePlus2, update: FilePen, delete: FileMinus2 };
const ICON_TONE = { create: "text-moss", update: "text-gold", delete: "text-clay" };

type Row = { kind: "add" | "del" | "ctx" | "hunk"; text: string; oldNo?: number; newNo?: number };

function parse(diff: string): Row[] {
  const rows: Row[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const line of diff.split("\n").slice(2)) {
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/);
    if (hunk) {
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[2]);
      rows.push({ kind: "hunk", text: line });
    } else if (line.startsWith("+")) {
      rows.push({ kind: "add", text: line.slice(1), newNo: newNo++ });
    } else if (line.startsWith("-")) {
      rows.push({ kind: "del", text: line.slice(1), oldNo: oldNo++ });
    } else {
      rows.push({ kind: "ctx", text: line.slice(1), oldNo: oldNo++, newNo: newNo++ });
    }
  }
  return rows;
}

const ROW_TONE = {
  add: "bg-moss-soft/70",
  del: "bg-clay-soft/70",
  ctx: "",
  hunk: "bg-sunken text-ink-3",
};
const MARK = { add: "+", del: "−", ctx: " ", hunk: " " };

export function FileDiff({ file }: { file: FileChange }) {
  const Icon = ICON[file.action];
  const rows = parse(file.diff);
  const added = rows.filter((r) => r.kind === "add").length;
  const removed = rows.filter((r) => r.kind === "del").length;
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-2 border-b border-line bg-paper/60 px-4 py-2.5">
        <Icon className={cx("size-4 shrink-0", ICON_TONE[file.action])} />
        <span className="min-w-0 truncate font-mono text-[13px] font-medium">{file.path}</span>
        <span className="ml-auto font-mono text-xs whitespace-nowrap">
          <span className="text-moss">+{added}</span> <span className="text-clay">−{removed}</span>
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-[12.5px] leading-[1.6]">
          <tbody>
            {rows.map((row, index) =>
              row.kind === "hunk" ? (
                <tr key={index} className={ROW_TONE.hunk}>
                  <td colSpan={4} className="px-4 py-0.5 text-[11.5px]">{row.text}</td>
                </tr>
              ) : (
                <tr key={index} className={ROW_TONE[row.kind]}>
                  <td className="w-10 select-none px-2 text-right text-ink-3/70">{row.oldNo}</td>
                  <td className="w-10 select-none px-2 text-right text-ink-3/70">{row.newNo}</td>
                  <td className="w-4 select-none text-ink-3">{MARK[row.kind]}</td>
                  <td className="pr-4 whitespace-pre">{row.text || " "}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
        {rows.length === 0 && <p className="px-4 py-3 text-sm text-ink-3">Empty file</p>}
      </div>
    </div>
  );
}
