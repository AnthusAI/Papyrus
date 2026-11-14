import { DateTime } from "luxon";
export const ZONE = "America/New_York";
export type Status = "scheduled" | "published" | "review";
export const STATUS_LABEL: Record<Status, string> = { scheduled: "Scheduled", published: "Published", review: "Needs review" };
export type Item = { id: string; title: string; status: Status; startUtc: string };
export function makeItems(): Item[] {
  const base = DateTime.now().setZone(ZONE).startOf("week"); // Monday
  const statuses: Status[] = ["scheduled", "published", "review"];
  const items: Item[] = [];
  for (let i = 1; i <= 30; i++) {
    const day = (i * 5) % 14; // spread across this + next week
    const hour = 7 + ((i * 3) % 12);
    const minute = (i % 2) * 30;
    const dt = base.plus({ days: day }).set({ hour, minute });
    items.push({ id: `f${i}`, title: `FAKE: Sample story ${String(i).padStart(2, "0")}`, status: statuses[i % 3], startUtc: dt.toUTC().toISO()! });
  }
  return items;
}
