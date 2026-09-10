import { cn } from "./utils";

/** List-row selection: dark copy on moss/paper tint in light mode; light copy on wash in dark mode. Never invert to primary-foreground. */
export const NEWSROOM_LIST_ROW_BASE =
  "w-full rounded-xl border bg-card p-4 text-left text-foreground transition-colors";

export const NEWSROOM_LIST_ROW_INACTIVE =
  "border-border hover:border-primary/30 hover:bg-primary/5";

export const NEWSROOM_LIST_ROW_ACTIVE =
  "border-primary/40 bg-primary/10 text-foreground ring-1 ring-primary/15";

export const NEWSROOM_INBOX_ROW_BASE =
  "flex items-start gap-3 rounded-xl border bg-card p-3 text-foreground transition-colors";

export const NEWSROOM_INBOX_ROW_INACTIVE =
  "border-border hover:border-primary/30 hover:bg-primary/5";

export const NEWSROOM_INBOX_ROW_ACTIVE =
  "border-primary/40 bg-primary/10 text-foreground ring-1 ring-primary/15";

export const NEWSROOM_SIDEBAR_NAV_ACTIVE =
  "bg-primary/10 text-foreground shadow-none hover:bg-primary/15";

export const NEWSROOM_SIDEBAR_NAV_INACTIVE =
  "text-muted-foreground hover:bg-muted/50 hover:text-foreground";

export function newsroomListRowClassName(active: boolean, className?: string): string {
  return cn(
    NEWSROOM_LIST_ROW_BASE,
    active ? NEWSROOM_LIST_ROW_ACTIVE : NEWSROOM_LIST_ROW_INACTIVE,
    className,
  );
}

export function newsroomInboxRowClassName(active: boolean, className?: string): string {
  return cn(
    NEWSROOM_INBOX_ROW_BASE,
    active ? NEWSROOM_INBOX_ROW_ACTIVE : NEWSROOM_INBOX_ROW_INACTIVE,
    className,
  );
}
