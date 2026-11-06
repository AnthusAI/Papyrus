/**
 * What the Newsroom's Add dialog does with an address: register it as a pending Reference (`intakePendingReferences`, the same action the
 * CLI's catalog intake uses), then, if the editor chose to, record their own decision on it. The accept goes through `reviewReferenceCuration`
 * and the rating through `setReferenceStars`, both from the Newsroom session, so they are the editor's own human decision and train the site's
 * Cyclotron like any other. The three calls are injected so the order and the partial-failure wording are tested without a network.
 */
export const ADD_REFERENCE_STAR_CHOICES = [1, 2, 3, 4, 5] as const;

export type AddReferenceInput = {
  url: string;
  /** Accept the Reference right away. Off leaves it pending for review. */
  accept: boolean;
  /** An optional 1 to 5 rating; null leaves it unrated. */
  stars: number | null;
  /** An optional sentence that rides on the accept. */
  note: string;
};

export type RegisteredReference = { id: string; curationStatus: string | null; reusedExisting: boolean };

export type AddReferenceDeps = {
  register: (url: string) => Promise<RegisteredReference>;
  accept: (referenceId: string, note: string) => Promise<void>;
  rate: (referenceId: string, stars: number) => Promise<void>;
};

export type AddReferenceOutcome = {
  referenceId: string;
  /** The address was already a Reference, so nothing new was created. */
  alreadyThere: boolean;
  accepted: boolean;
  stars: number | null;
  /** Steps after the Reference existed that did not save, in plain words. */
  problems: string[];
};

/** The https address an editor typed, without its fragment. Throws a plain message for anything else. */
export function normalizeAddUrl(raw: string): string {
  let parsed: URL | null = null;
  try {
    parsed = new URL(raw.trim());
  } catch {
    parsed = null;
  }
  if (!parsed || parsed.protocol !== "https:") throw new Error("Paste an https address.");
  parsed.hash = "";
  return parsed.toString();
}

export function normalizeAddStars(value: number | null): number | null {
  if (value === null) return null;
  if (!Number.isInteger(value) || value < 1 || value > 5) throw new Error("A rating is 1 to 5 stars.");
  return value;
}

function reason(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function addReference(input: AddReferenceInput, deps: AddReferenceDeps): Promise<AddReferenceOutcome> {
  const url = normalizeAddUrl(input.url);
  const stars = normalizeAddStars(input.stars);
  const registered = await deps.register(url);
  const problems: string[] = [];
  let accepted = registered.curationStatus === "accepted";
  if (input.accept && !accepted) {
    try {
      await deps.accept(registered.id, input.note.trim());
      accepted = true;
    } catch (error) {
      problems.push(`It was added, but accepting it did not save: ${reason(error)}`);
    }
  }
  let rated: number | null = null;
  if (stars !== null) {
    try {
      await deps.rate(registered.id, stars);
      rated = stars;
    } catch (error) {
      problems.push(`It was added, but the ${stars}-star rating did not save: ${reason(error)}`);
    }
  }
  return { referenceId: registered.id, alreadyThere: registered.reusedExisting, accepted: input.accept && accepted, stars: rated, problems };
}

/** Reads the `intakePendingReferences` answer (a JSON string or object) into the one Reference it names. Throws the server's own reason when refused. */
export function parseIntakeAnswer(raw: unknown): RegisteredReference {
  let answer: unknown = raw;
  if (typeof raw === "string") {
    try {
      answer = JSON.parse(raw);
    } catch {
      throw new Error("The newsroom's answer could not be read. Try again.");
    }
  }
  const body = answer as { ok?: boolean; errors?: Array<{ message?: string }>; references?: Array<Record<string, unknown>> } | null;
  if (!body || body.ok !== true) {
    throw new Error(body?.errors?.[0]?.message ?? "The newsroom did not accept this address.");
  }
  const first = body.references?.[0];
  if (!first || typeof first.id !== "string") throw new Error("The newsroom did not name the new Reference. Try again.");
  return {
    id: first.id,
    curationStatus: typeof first.curationStatus === "string" ? first.curationStatus : null,
    reusedExisting: first.reusedExisting === true,
  };
}

/** What the dialog tells the editor after a successful add. */
export function addedMessage(outcome: AddReferenceOutcome): string {
  const parts = [outcome.alreadyThere ? "This address was already a Reference." : "Added to References."];
  if (outcome.accepted) parts.push("Accepted.");
  if (outcome.stars !== null) parts.push(`Rated ${outcome.stars} of 5 stars.`);
  if (!outcome.accepted && outcome.stars === null && !outcome.problems.length) parts.push("It is pending review.");
  return parts.join(" ");
}
