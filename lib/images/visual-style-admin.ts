/**
 * The logic behind Administration > Policies > Visual style, apart from React: what a profile document holds, how an image type is added, retired, reordered and
 * described, and how the effective rules are labelled with where each came from (project/wiki/image-toolchain.md sections 5.2, 5.8 and 8).
 * Every change is a partial document laid over the current profile by `image_profile_save` (objects merge, lists replace, null removes a key).
 */

export type Profile = Record<string, any>;
export type Source = "figure-system" | "stock" | "generated";
export type Example = { attachmentId: string; kind: "exemplar" | "negative"; note?: string; sendToProvider?: boolean; sha256?: string; mediaType?: string; addedBy?: string; addedByKind?: string };
export type ImageTypeRow = {
  key: string; label: string; description: string; family: string; useLabel: string; use: string | null; thumbnail: boolean | null; smallestWidthPx: number | null;
  sources: Source[]; exampleCount: number; retired: boolean; extendsKey: string | null; inheritsFrom: string | null;
};

export const IDENTITY_SCOPE = "identity";
export const MAX_PICTURE_BYTES = 10 * 1024 * 1024;
export const PICTURE_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const SOURCE_LABELS: Record<Source, { label: string; detail: string }> = {
  "figure-system": { label: "Figure system", detail: "Drawn with the figure tools, never generated" },
  stock: { label: "Stock", detail: "Rights-cleared pictures from other sources" },
  generated: { label: "Generated", detail: "Made by the image model" },
};
export const USE_LABELS: Record<string, string> = { cover: "Headline picture", inline: "In the article", social: "Social card" };
export const REVIEW_CHOICES = [
  { value: "before_publish", label: "Before publishing", detail: "A picture added without a person must be reviewed before readers see it. Publishing waits for the review." },
  { value: "after_the_fact", label: "After the fact", detail: "Publishing goes ahead; the picture waits in the review queue until a person keeps, swaps or removes it." },
] as const;
export const NO_STYLE_WARNING = "This publication has no image style guidelines, so generated images will look unpredictable. Add guidelines and example pictures here.";

const asObject = (value: unknown): Record<string, any> => (value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, any>) : {});
export const textLines = (text: string): string[] => text.split("\n").map((line) => line.trim()).filter(Boolean);

export function typeDefinitions(profile: Profile | null): Record<string, Profile> {
  return asObject(profile?.imageTypes);
}

/** The key of the type a field comes from, walking `extends` (the type itself first). */
function ancestry(profile: Profile, key: string): string[] {
  const types = typeDefinitions(profile);
  const chain: string[] = [];
  for (let current: string | undefined = key; current && types[current] && !chain.includes(current); current = types[current].extends) chain.push(current);
  return chain;
}

export function effectiveUse(profile: Profile, key: string): string | null {
  const types = typeDefinitions(profile);
  for (const candidate of ancestry(profile, key)) if (types[candidate].use) return types[candidate].use;
  return null;
}

export function imageTypeRows(profile: Profile | null): ImageTypeRow[] {
  if (!profile) return [];
  const types = typeDefinitions(profile);
  const treatments = asObject(profile.treatments);
  return Object.entries(types).map(([key, definition]) => {
    const chain = ancestry(profile, key);
    const first = <T,>(pick: (item: Profile) => T | undefined): T | undefined => {
      for (const candidate of chain) { const found = pick(types[candidate]); if (found !== undefined) return found; }
      return undefined;
    };
    const treatment = first((item) => item.treatment);
    const use = effectiveUse(profile, key);
    const display = first((item) => (item.display ? item.display : undefined)) as Profile | undefined;
    return {
      key, label: definition.label || key, description: definition.description || "", family: treatment ? treatments[treatment]?.label || treatment : "Not set", use,
      useLabel: use ? USE_LABELS[use] || use : "Not set", thumbnail: typeof display?.thumbnail === "boolean" ? display.thumbnail : null,
      smallestWidthPx: typeof display?.smallestWidthPx === "number" ? display.smallestWidthPx : null,
      sources: (first((item) => item.sources) as Source[] | undefined) ?? [], exampleCount: (definition.examples ?? []).length, retired: definition.retired === true,
      extendsKey: definition.extends ?? null, inheritsFrom: definition.extends ? types[definition.extends]?.label || definition.extends : null,
    };
  });
}

/** A key from a plain-words name: lowercase words with hyphens. */
export function keyFromLabel(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export type NewTypeInput = { label: string; description: string; startFrom: string | null; use: "cover" | "inline" | "social"; key?: string };

/** The partial document that adds a type, and the problem (in words) when it cannot be added. */
export function addTypeDocument(profile: Profile | null, input: NewTypeInput): { document?: Profile; key?: string; problem?: string } {
  const types = typeDefinitions(profile);
  const key = (input.key || keyFromLabel(input.label)).trim();
  if (!input.label.trim()) return { problem: "Give the type a name." };
  if (!key) return { problem: "The name needs at least one letter or number." };
  if (types[key]) return { problem: `There is already a type called ${types[key].label || key}. Choose another name.` };
  const definition: Profile = { label: input.label.trim(), description: input.description.trim() };
  if (input.startFrom) {
    if (!types[input.startFrom]) return { problem: "The type to start from is not in this profile." };
    definition.extends = input.startFrom;
    if (effectiveUse(profile as Profile, input.startFrom) !== input.use) definition.use = input.use;
  } else {
    definition.use = input.use;
    definition.sources = ["stock", "generated"];
  }
  return { key, document: { imageTypes: { [key]: definition } } };
}

export function retireDocument(key: string, retired: boolean): Profile {
  return { imageTypes: { [key]: { retired } } };
}

/** Move one source up or down in a type's preference order. */
export function moveSource(sources: Source[], index: number, direction: -1 | 1): Source[] {
  const target = index + direction;
  if (target < 0 || target >= sources.length) return sources;
  const next = [...sources];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export const unusedSources = (sources: Source[]): Source[] => (Object.keys(SOURCE_LABELS) as Source[]).filter((source) => !sources.includes(source));

export function examplesFor(profile: Profile | null, scope: string): Example[] {
  if (!profile) return [];
  return (scope === IDENTITY_SCOPE ? asObject(profile.identity).examples : typeDefinitions(profile)[scope]?.examples) ?? [];
}

/** Why a file cannot be an example picture, in words, or null when it can. */
export function pictureProblem(file: { name: string; type: string; size: number }): string | null {
  if (!PICTURE_TYPES.includes(file.type)) return `${file.name} is not a PNG, JPEG or WebP picture. Those are the only types example pictures can be.`;
  if (file.size > MAX_PICTURE_BYTES) return `${file.name} is ${(file.size / (1024 * 1024)).toFixed(1)} MB. Example pictures must be 10 MB or smaller.`;
  return null;
}

export function extensionFor(type: string): string {
  return type === "image/png" ? "png" : type === "image/jpeg" ? "jpg" : "webp";
}

/** The words for a layer name in `fieldSources` ("publication", "treatment:editorial-illustration", "image-type:cover-illustration"). */
export function describeSource(source: string, profile: Profile | null, ownKey: string): string {
  const [layer, key = ""] = source.split(":");
  const types = typeDefinitions(profile);
  if (layer === "publication") return "Brand";
  if (layer === "treatment") return `Family: ${asObject(profile?.treatments)[key]?.label || key}`;
  if (layer === "use") return `Use: ${USE_LABELS[key] || key}`;
  if (layer === "image-type") return key === ownKey ? "This type" : `Parent type: ${types[key]?.label || key}`;
  if (layer === "section") return `Section: ${key}`;
  if (layer === "story") return "This Story";
  return source;
}

/** "avoid:'small details' by image-type:inline-illustration" in words. */
function describeRemoval(entry: string, profile: Profile | null, ownKey: string): string {
  const [what, by = ""] = entry.split(" by ");
  const who = by ? describeSource(by, profile, ownKey).replace(/^Parent type: /, "") : "a type";
  const subject = what.startsWith("avoid:") ? `Avoid ${what.slice("avoid:".length)}` : what === "safeZones" ? "Safe zones" : what;
  return `${subject} (taken off by ${who === "This type" ? "this type" : who})`;
}

export type EffectiveLine = { text: string; source: string };
export type EffectiveView = {
  masterPrompt: EffectiveLine | null; guidance: EffectiveLine[]; avoid: EffectiveLine[]; sizes: EffectiveLine | null; display: EffectiveLine | null; sources: EffectiveLine | null;
  removed: string[]; constraints: { id: string; text: string }[];
};

/** The resolved style of one type as lines that each say where they came from. */
export function effectiveView(resolved: Profile, profile: Profile | null, key: string): EffectiveView {
  const effective = asObject(resolved.effective);
  const fieldSources = asObject(resolved.fieldSources);
  const from = (field: string) => describeSource(String(fieldSources[field] ?? "publication"), profile, key);
  const lines = (name: string): EffectiveLine[] => ((effective[name] as string[] | undefined) ?? []).map((text, index) => ({ text, source: from(`${name}[${index}]`) }));
  const sizes = effective.sizes ? `${effective.sizes.aspectRatio}, ${effective.sizes.width} by ${effective.sizes.height}` : null;
  const display = effective.display
    ? [effective.display.where, effective.display.smallestWidthPx ? `shown as small as ${effective.display.smallestWidthPx}px` : null,
       effective.display.thumbnail === true ? "shown as a thumbnail" : effective.display.thumbnail === false ? "never a thumbnail" : null].filter(Boolean).join(", ")
    : null;
  return {
    masterPrompt: effective.masterPrompt ? { text: effective.masterPrompt, source: from("masterPrompt") } : null,
    guidance: lines("guidance"), avoid: lines("avoid"),
    sizes: sizes ? { text: sizes, source: from("sizes") } : null, display: display ? { text: display, source: from("display") } : null,
    sources: effective.sources ? { text: (effective.sources as Source[]).map((source) => SOURCE_LABELS[source]?.label || source).join(", then "), source: from("sources") } : null,
    removed: ((fieldSources.removed as string[] | undefined) ?? []).map((entry) => describeRemoval(entry, profile, key)),
    constraints: ((resolved.constraints as Profile[] | undefined) ?? []).map((item) => ({ id: item.id, text: item.text })),
  };
}

/** Where a safe zone's region sits on the sample frame, as percentages, when its words say so. */
export function safeZoneBox(region: string): { top: number; left: number; width: number; height: number } | null {
  const words = region.toLowerCase();
  if (words.includes("upper third") || words.includes("top third")) return { top: 0, left: 0, width: 100, height: 33.3 };
  if (words.includes("lower third") || words.includes("bottom third")) return { top: 66.7, left: 0, width: 100, height: 33.3 };
  if (words.includes("left third")) return { top: 0, left: 0, width: 33.3, height: 100 };
  if (words.includes("right third")) return { top: 0, left: 66.7, width: 33.3, height: 100 };
  return null;
}

export function ratioOf(aspect: string | undefined): number {
  const [width, height] = (aspect || "16:9").split(":").map(Number);
  return width > 0 && height > 0 ? width / height : 16 / 9;
}
