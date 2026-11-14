/**
 * An in-browser stand-in for the image-service door, for the Visual style page's browser test and screenshots only: the same operations and answers the real door gives
 * (profile get, resolve, save, init, example add and remove), kept in memory. It reads and writes nothing outside the page.
 */
type Profile = Record<string, any>;

const svg = (background: string, shapes: string) => `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><rect width="160" height="90" fill="${background}"/>${shapes}</svg>`)}`;
const PICTURES: Record<string, string> = {
  "fixture-calm": svg("#e9ecf0", `<circle cx="120" cy="80" r="46" fill="#dce3ec"/><rect x="44" y="52" width="26" height="26" rx="5" fill="#14181f"/>`),
  "fixture-moon": svg("#dce3ec", `<circle cx="40" cy="-4" r="40" fill="#1f2a44"/><rect x="96" y="54" width="28" height="22" rx="5" fill="#14181f"/>`),
  "fixture-photoreal": svg("#555", `<defs><radialGradient id="g"><stop offset="0" stop-color="#ddd"/><stop offset="1" stop-color="#222"/></radialGradient></defs><circle cx="80" cy="45" r="44" fill="url(#g)"/>`),
  "fixture-busy": svg("#e7e1d4", Array.from({ length: 24 }, (_, index) => `<rect x="${6 + (index % 8) * 19}" y="${8 + Math.floor(index / 8) * 27}" width="12" height="12" rx="2" fill="${index % 3 ? "#1f2a44" : "#565d68"}"/>`).join("")),
};

export const FIXTURE_PROFILE: Profile = {
  schemaVersion: 2,
  imageReview: "after_the_fact",
  identity: {
    summary: "Neutral, like a newspaper: flat shapes on cool paper, with ink blue as the only strong colour.",
    masterPrompt: "Flat shapes with generous rounded corners. No perspective, no gradient, no texture and no outlines. People are silhouettes with no faces.",
    palette: [
      { name: "Panel", hex: "#e9ecf0", token: "panel", role: "ground" }, { name: "Card", hex: "#ffffff", token: "card", role: "inset" },
      { name: "Machine tint", hex: "#dce3ec", token: "machine" }, { name: "Human tint", hex: "#e7e1d4", token: "human" },
      { name: "Ink blue", hex: "#1f2a44", token: "brand", role: "brand" }, { name: "Ink", hex: "#14181f", token: "ink", role: "focal" },
    ],
    paletteLimit: 6, mood: ["calm", "plain", "precise"],
    examples: [{ attachmentId: "fixture-moon", kind: "exemplar", note: "The whole brand in one picture: a disc, one subject.", sendToProvider: true }],
  },
  techniques: { preferred: ["flat shapes", "one large disc cropped by the canvas edge"], avoided: ["perspective", "gradients", "texture"] },
  subjects: { representation: "People are silhouettes with no faces.", never: [] },
  treatments: {
    diagram: { label: "Diagram", guidance: "Explains a relationship. Drawn with the figure tools, never generated." },
    "editorial-illustration": { label: "Editorial illustration", guidance: "A place or a moment, not an explanation." },
    photo: { label: "Photograph", guidance: "Authentic, rights-cleared photographs only." },
  },
  uses: { cover: { label: "Headline picture" }, inline: { label: "In the article" }, social: { label: "Social card" } },
  imageTypes: {
    "cover-diagram": {
      label: "Headline diagram", description: "A chunky diagram for the top of a Story that still reads as a small card thumbnail.", treatment: "diagram", use: "cover",
      display: { where: "article top and cards", smallestWidthPx: 160, thumbnail: true }, guidance: "At most four shapes, one inverted focal tile, words only if one word stays readable.",
      avoid: ["more than four shapes"], sizes: { aspectRatio: "16:9", width: 1360, height: 765 }, sources: ["figure-system"], examples: [],
    },
    "inline-diagram": {
      label: "Technical diagram", description: "A detailed diagram inside the article. Never shown as a thumbnail.", treatment: "diagram", use: "inline",
      display: { where: "article body", smallestWidthPx: 343, thumbnail: false }, guidance: "The full figure rules: nothing under 13px at 343px wide.", sources: ["figure-system"], examples: [],
    },
    "cover-photo": {
      label: "Headline photograph", description: "An authentic, rights-cleared photograph that is relevant to the Story.", treatment: "photo", use: "cover",
      display: { where: "article top and cards", smallestWidthPx: 160, thumbnail: true }, guidance: "Never implies it shows a person, place or event it does not.", sources: ["stock"], examples: [],
    },
    "cover-illustration": {
      label: "Headline illustration", description: "A simple, bold illustration for the top of a Story that still reads small.", treatment: "editorial-illustration", use: "cover",
      display: { where: "article top and cards", smallestWidthPx: 160, thumbnail: true }, guidance: "A flat side elevation. One large disc cropped by the edge, exactly one subject in the focal colour in the lower third.",
      avoid: ["small details", "more than one subject", "a real person"], sizes: { aspectRatio: "16:9", width: 1920, height: 1080 },
      safeZones: [{ region: "upper third", instruction: "Keep the upper third quiet, for the card's title." }], sources: ["stock", "generated"],
      examples: [
        { attachmentId: "fixture-calm", kind: "exemplar", note: "The calm we want: one disc, one subject.", sendToProvider: true },
        { attachmentId: "fixture-busy", kind: "negative", note: "Too many small shapes: this turns to mush at card size.", sendToProvider: false },
        { attachmentId: "fixture-photoreal", kind: "negative", note: "Looks like a photograph. Never generate this.", sendToProvider: false },
      ],
    },
    "inline-illustration": {
      extends: "cover-illustration", label: "Illustration in the article", description: "A larger illustration inside the article that can carry more detail and mood.", use: "inline",
      display: { where: "article body", smallestWidthPx: 343, thumbnail: false }, guidance: "Several elements may share the scene; still one focal subject.",
      removeFromParent: { avoid: ["small details"], safeZones: true }, sources: ["generated", "stock"], examples: [],
    },
    "social-card": {
      extends: "cover-illustration", label: "Social card", description: "The picture in link previews on other sites.", use: "social",
      display: { where: "link previews", smallestWidthPx: 120, thumbnail: true }, sizes: { aspectRatio: "1.91:1", width: 1200, height: 630 }, examples: [],
    },
  },
  typePreference: { cover: ["cover-diagram", "cover-photo", "cover-illustration"], inline: null, social: ["social-card"] },
  constraints: [{
    id: "no-photoreal-generated", version: 1, appliesTo: { origins: ["generated"] }, prohibits: { treatments: ["photo"] },
    text: "Generated pictures must be unmistakably illustrations. Nothing generated may look like a documentary photograph.", promptDirective: "Unmistakably an illustration.", promptAvoid: ["photograph"],
  }],
};

const isObject = (value: unknown): value is Profile => !!value && typeof value === "object" && !Array.isArray(value);
function merge(base: Profile, patch: Profile): Profile {
  const result: Profile = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete result[key];
    else if (isObject(value) && isObject(result[key])) result[key] = merge(result[key], value);
    else result[key] = JSON.parse(JSON.stringify(value));
  }
  return result;
}

function chainOf(profile: Profile, key: string): string[] {
  const types = profile.imageTypes ?? {};
  const chain: string[] = [];
  for (let current: string | undefined = key; current && types[current] && !chain.includes(current); current = types[current].extends) chain.push(current);
  return chain.reverse();
}

function resolve(profile: Profile, use: string, key: string) {
  const types = profile.imageTypes ?? {};
  if (!types[key] || types[key].retired) return { ok: false, error: { code: "image_type_unknown", message: `There is no image type ${key}, or it has been retired.`, retryable: false, details: {} } };
  const chain = chainOf(profile, key);
  const field: Record<string, any> = {};
  const guidance: string[] = []; const avoid: string[] = []; const removed: string[] = [];
  const treatmentKey = [...chain].reverse().map((item) => types[item].treatment).find(Boolean);
  const identity = profile.identity ?? {};
  (profile.techniques?.avoided ?? []).forEach((text: string) => { field[`avoid[${avoid.length}]`] = "publication"; avoid.push(text); });
  (profile.subjects?.never ?? []).forEach((text: string) => { field[`avoid[${avoid.length}]`] = "publication"; avoid.push(text); });
  if (treatmentKey && profile.treatments?.[treatmentKey]?.guidance) { field[`guidance[${guidance.length}]`] = `treatment:${treatmentKey}`; guidance.push(profile.treatments[treatmentKey].guidance); }
  const layers: any[] = [{ layer: "publication" }, ...(treatmentKey ? [{ layer: "treatment", key: treatmentKey }] : []), { layer: "use", key: use }];
  for (const item of chain) {
    const definition = types[item];
    layers.push({ layer: "image-type", key: item, ...(item === key ? {} : { via: "extends" }) });
    if (definition.guidance) { field[`guidance[${guidance.length}]`] = `image-type:${item}`; guidance.push(definition.guidance); }
    for (const text of definition.removeFromParent?.avoid ?? []) { const at = avoid.indexOf(text); if (at >= 0) { avoid.splice(at, 1); removed.push(`avoid:'${text}' by image-type:${item}`); } }
    for (const text of definition.avoid ?? []) { if (!avoid.includes(text)) { field[`avoid[${avoid.length}]`] = `image-type:${item}`; avoid.push(text); } }
  }
  const pick = (name: string) => { for (const item of [...chain].reverse()) if (types[item][name] !== undefined) { field[name] = `image-type:${item}`; return types[item][name]; } return undefined; };
  const sizes = pick("sizes"); const display = pick("display"); const sources = pick("sources");
  field.masterPrompt = "publication";
  return { ok: true, op: "image_profile_resolve", publication: "fixture", warnings: [], result: {
    layers, imageType: key, imageTypeChosenBy: "request", availableTypes: [], resolutionHash: "sha256:fixture",
    effective: { masterPrompt: identity.masterPrompt, guidance, avoid, sizes, display, sources, palette: identity.palette, use },
    fieldSources: { ...field, ...(removed.length ? { removed } : {}) }, constraints: profile.constraints ?? [],
  } };
}

export function createFixtureBackend(scenario: string) {
  let profile: Profile | null = scenario === "none" ? null : JSON.parse(JSON.stringify(FIXTURE_PROFILE));
  let version = profile ? 3 : 0;
  const pictures: Record<string, string> = { ...PICTURES };
  const attachments: Record<string, { role: string; sha: string; mediaType: string; size: number }> = {};
  const calls: { op: string; input: any }[] = [];
  const fail = (code: string, message: string, details: any = {}) => ({ ok: false, op: "x", error: { code, message, retryable: false, details } });
  const itemId = () => `item-editorial-doctrine-visual-style-v${version}`;
  const save = (document: Profile, guard: string, reason: string) => {
    if (guard !== (profile ? itemId() : "none")) return fail("stale_version", "The profile has changed since you read it.", { currentVersionId: profile ? itemId() : "none" });
    const next = merge(profile ?? {}, document);
    if (JSON.stringify(next) === JSON.stringify(profile)) return { ok: true, op: "image_profile_save", publication: "fixture", warnings: [], result: { itemId: itemId(), versionNumber: version, contentHash: "x", unchanged: true } };
    profile = next; version += 1; void reason;
    return { ok: true, op: "image_profile_save", publication: "fixture", warnings: [], result: { itemId: itemId(), versionNumber: version, contentHash: "x" } };
  };
  const door = async (op: string, input: any) => {
    calls.push({ op, input });
    await new Promise((resolveTimer) => setTimeout(resolveTimer, 5));
    if (op === "image_profile_get") return profile ? { ok: true, op, publication: "fixture", warnings: [], result: { profile: JSON.parse(JSON.stringify(profile)), itemId: itemId(), versionNumber: version, updatedAt: "2026-11-07T17:51:39Z", updatedBy: "Ryan", contentHash: "x" } } : fail("not_found", "This publication has no visual style profile yet.");
    if (op === "image_profile_save") return save(input.document, input.expectedCurrentVersionId, input.reason);
    if (op === "image_profile_resolve") return resolve(profile ?? {}, input.use, input.imageType);
    if (op === "image_profile_init") return { ok: true, op, publication: "fixture", warnings: [], result: {
      expectedCurrentVersionId: "none", profileExists: false,
      document: { schemaVersion: 2, imageTypes: { "cover-picture": { label: "Headline picture", description: "The picture at the top of a Story and on its cards.", use: "cover", sources: ["stock", "generated"] }, "inline-picture": { label: "Picture in the article", description: "A picture inside the article body.", use: "inline", sources: ["stock", "generated"] }, "social-card": { label: "Social card", description: "The picture in link previews on other sites.", use: "social", sources: ["stock", "generated"] } } },
      notes: ["No brand colours were given, so identity.palette is empty. Add the brand colours.", "Write identity.summary and identity.masterPrompt: how this publication's pictures should look, in your own words.", "Choose imageReview: before_publish (the default) or after_the_fact."] } };
    if (op === "image_profile_example_add") {
      const attachment = attachments[input.attachmentId];
      if (!attachment) return fail("not_found", `No uploaded picture ${input.attachmentId}.`);
      const scope = input.imageType === "identity" ? null : profile!.imageTypes[input.imageType];
      if (input.imageType !== "identity" && (!scope || scope.retired)) return fail("image_type_unknown", `There is no image type ${input.imageType}.`);
      const list = input.imageType === "identity" ? profile!.identity.examples ?? [] : scope.examples ?? [];
      const entry = { attachmentId: input.attachmentId, sha256: attachment.sha, kind: input.kind, note: input.note, sendToProvider: !!input.sendToProvider };
      const document = input.imageType === "identity" ? { identity: { examples: [...list, entry] } } : { imageTypes: { [input.imageType]: { examples: [...list, entry] } } };
      const saved: any = save(document, input.expectedCurrentVersionId, input.reason);
      return saved.ok ? { ...saved, op, result: { attachmentId: input.attachmentId, sha256: `sha256:${attachment.sha}`, versionNumber: version, imageType: input.imageType } } : saved;
    }
    if (op === "image_profile_example_remove") {
      const scopes = [["identity", profile!.identity.examples ?? []], ...Object.entries(profile!.imageTypes).map(([key, value]: [string, any]) => [key, value.examples ?? []])] as [string, any[]][];
      const hit = scopes.filter(([scope, list]) => (!input.imageType || input.imageType === scope) && list.some((entry) => entry.attachmentId === input.attachmentId));
      if (!hit.length) return fail("not_found", "That picture is not listed.");
      let document: Profile = {};
      for (const [scope, list] of hit) document = merge(document, scope === "identity" ? { identity: { examples: list.filter((entry) => entry.attachmentId !== input.attachmentId) } } : { imageTypes: { [scope]: { examples: list.filter((entry) => entry.attachmentId !== input.attachmentId) } } });
      const saved: any = save(document, input.expectedCurrentVersionId, input.reason);
      return saved.ok ? { ...saved, op, result: { versionNumber: version, removedFrom: hit.map(([scope]) => scope) } } : saved;
    }
    return fail("not_implemented", `${op} is not part of this fixture.`);
  };
  const upload = async (file: File, kind: "exemplar" | "negative") => {
    const id = `fixture-upload-${Object.keys(attachments).length + 1}`;
    attachments[id] = { role: kind === "exemplar" ? "visual_example" : "visual_negative", sha: id.padEnd(64, "0"), mediaType: file.type, size: file.size };
    pictures[id] = svg("#e7e1d4", `<circle cx="80" cy="45" r="30" fill="#1f2a44"/>`);
    return { attachmentId: id };
  };
  const url = async (id: string) => pictures[id] ?? null;
  return { door: door as any, upload, url, calls, current: () => profile, version: () => version, injectConcurrentChange: () => { profile = merge(profile ?? {}, { identity: { mood: ["calm", "plain"] } }); version += 1; } };
}
