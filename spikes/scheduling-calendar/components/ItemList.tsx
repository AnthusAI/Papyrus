import { DateTime } from "luxon";
import { ZONE, type Item } from "../lib/data";
import { StatusBadge } from "./StatusBadge";
export function ItemList({ items }: { items: Item[] }) {
  const sorted = [...items].sort((a, b) => a.startUtc.localeCompare(b.startUtc));
  return (
    <section aria-labelledby="list-h">
      <h2 id="list-h">All scheduled items ({ZONE})</h2>
      <ul className="plain">
        {sorted.map((i) => (
          <li key={i.id}>
            <a href={`#${i.id}`}><time dateTime={i.startUtc}>{DateTime.fromISO(i.startUtc).setZone(ZONE).toFormat("ccc d LLL, h:mm a")}</time> {i.title}</a>
            <StatusBadge status={i.status} />
          </li>
        ))}
      </ul>
    </section>
  );
}
