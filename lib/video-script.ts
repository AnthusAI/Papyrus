export type VideoElementAliases = Record<string, string>;

/**
 * Rewrites generic VideoML element names in a stored script to the publication's
 * own scene components, e.g. `{ "quote-card": "acme-quote-card" }`.
 */
export function normalizeDevPreviewDsl(dsl: string, elementAliases: VideoElementAliases = {}): string {
  let normalized = dsl;
  for (const [generic, branded] of Object.entries(elementAliases)) {
    const escaped = generic.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    normalized = normalized.replace(new RegExp(`(</?)${escaped}(?=[\\s/>])`, "g"), `$1${branded}`);
  }
  return normalized;
}

export type VideoScriptTargetKind = "article" | "edition";

export type VideoScriptRef = {
  slug: string;
  dsl: string;
  targetKind: VideoScriptTargetKind;
};

export function videomlItemSlug(targetSlug: string): string {
  return `${targetSlug}--videoml`;
}

export function parseVideoScriptRef(item: {
  slug: string;
  editorial?: unknown;
}): VideoScriptRef | null {
  const editorial = parseEditorial(item.editorial);
  const videoScript = editorial?.videoScript;
  if (!videoScript || typeof videoScript !== "object" || Array.isArray(videoScript)) return null;

  const scriptRecord = videoScript as Record<string, unknown>;
  const dsl = typeof scriptRecord.dsl === "string" ? scriptRecord.dsl.trim() : "";
  if (!dsl) return null;

  const target = scriptRecord.target;
  const targetKind: VideoScriptTargetKind =
    target && typeof target === "object" && !Array.isArray(target) && (target as Record<string, unknown>).kind === "edition"
      ? "edition"
      : "article";

  return { slug: item.slug, dsl, targetKind };
}

function parseEditorial(editorial: unknown): Record<string, unknown> | null {
  if (!editorial) return null;
  if (typeof editorial === "string") {
    try {
      const parsed = JSON.parse(editorial) as unknown;
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }
  if (typeof editorial === "object" && !Array.isArray(editorial)) {
    return editorial as Record<string, unknown>;
  }
  return null;
}
