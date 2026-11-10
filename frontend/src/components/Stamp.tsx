import { motion } from "motion/react";
import { fullTime } from "../lib/format";
import { cx } from "./ui";

const STYLE: Record<string, { text: string; label: string }> = {
  executed: { text: "text-moss border-moss", label: "Approved" },
  approved: { text: "text-moss border-moss", label: "Approved" },
  failed: { text: "text-gold border-gold", label: "Approved, not delivered" },
  rejected: { text: "text-clay border-clay", label: "Rejected" },
  changes_requested: { text: "text-ocean border-ocean", label: "Sent back" },
};

/** The mark a human decision leaves on a proposal. */
export function Stamp({ status, by, at }: { status: string; by: string; at: string }) {
  const style = STYLE[status];
  if (!style) return null;
  return (
    <motion.div
      initial={{ opacity: 0, scale: 1.7, rotate: -9 }}
      animate={{ opacity: 1, scale: 1, rotate: -3 }}
      transition={{ type: "spring", stiffness: 520, damping: 22 }}
      className={cx("inline-block rounded-md border-2 px-3.5 py-2", style.text)}
    >
      <div className="text-sm font-extrabold tracking-[0.14em] uppercase">{style.label}</div>
      <div className="mt-0.5 font-mono text-[11px] leading-snug">
        {by}
        <br />
        {fullTime(at)}
      </div>
    </motion.div>
  );
}
