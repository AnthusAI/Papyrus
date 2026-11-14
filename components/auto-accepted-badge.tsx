import { BotIcon } from "lucide-react";
import { AUTO_ACCEPT_RULE_ACTOR } from "../lib/reference-policy";
import { cn } from "@/lib/utils";

/**
 * Shown on a Reference accepted automatically: by the Cyclotron's confidence after the editors' usual time, or, for a monitor that delivers
 * by a fixed rule, on delivery ("by rule"). Words and an icon, never colour alone, and different from an editor's Accept.
 */
export function AutoAcceptedBadge({ actor, className, reason }: { actor?: string | null; className?: string; reason?: string | null }) {
  const byRule = (actor ?? "").trim() === AUTO_ACCEPT_RULE_ACTOR;
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full bg-[var(--feed-control)] px-2 py-0.5 text-[0.7rem] font-medium text-foreground", className)}
      data-auto-accepted={byRule ? "rule" : "cyclotron"}
      title={reason?.trim() || (byRule ? "The monitor's rule matched this item, so it was accepted on delivery. An editor can still Reject it." : "The Cyclotron accepted this automatically because nobody voted in the time editors usually take. An editor can still Reject it.")}
    >
      <BotIcon aria-hidden="true" className="size-3.5" />
      Accepted automatically{byRule ? " (by rule)" : ""}
    </span>
  );
}
