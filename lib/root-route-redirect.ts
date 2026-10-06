export type RootSearchParams = Record<string, string | string[] | undefined>;

export function buildRootRedirectTarget(destination: string, searchParams: RootSearchParams | undefined): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(searchParams ?? {})) {
    if (Array.isArray(value)) {
      for (const entry of value) query.append(name, entry);
    } else if (value !== undefined) {
      query.append(name, value);
    }
  }
  const serialized = query.toString();
  if (!serialized) return destination;
  const separator = destination.includes("?") ? "&" : "?";
  return `${destination}${separator}${serialized}`;
}
