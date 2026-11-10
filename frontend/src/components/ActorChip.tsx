import { Bot, Cog, UserRound } from "lucide-react";
import { AGENT_LABEL } from "../lib/format";
import { cx } from "./ui";

const STYLE = {
  human: { icon: UserRound, className: "bg-moss-soft text-moss" },
  agent: { icon: Bot, className: "bg-ocean-soft text-ocean" },
  system: { icon: Cog, className: "bg-sunken text-ink-2" },
};

export function ActorChip({ type, name }: { type: "agent" | "human" | "system"; name: string }) {
  const { icon: Icon, className } = STYLE[type];
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap", className)}>
      <Icon className="size-3.5" />
      {type === "agent" ? AGENT_LABEL[name] ?? name : type === "system" && (name === "countersign" || name === "foreman") ? "Countersign" : name}
    </span>
  );
}
