import { CalendarClock, CheckCircle2, AlertTriangle } from "lucide-react";
import type { Status } from "../lib/data";
import { STATUS_LABEL } from "../lib/data";
const ICON = { scheduled: CalendarClock, published: CheckCircle2, review: AlertTriangle };
export function StatusBadge({ status }: { status: Status }) {
  const I = ICON[status];
  return <span className="badge"><I size={13} aria-hidden="true" />{STATUS_LABEL[status]}</span>;
}
