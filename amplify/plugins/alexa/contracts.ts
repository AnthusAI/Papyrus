/**
 * The typed seams of the `alexa` plugin. Each one has an interface here and an index that wires an implementation in
 * (docs/alexa.md says where a later task adds its files).
 */
import type { RequestHandler } from "ask-sdk-core";
import type { AlexaConfig } from "./config";

/** One published story as the public site shows it. */
export type PublicStorySummary = {
  /** The PublishedItem id. */
  id: string;
  /** The story's slug: the key for `getStory` and, with the site origin, its public URL. */
  slug: string;
  title: string;
  deck?: string;
  byline?: string;
  /** ISO 8601. */
  publishedAt: string;
};

export type PublicStory = PublicStorySummary & {
  /** The story's Markus source, verbatim (the `.md` twin of its page, or `bodyMarkus`). Parse it; never treat it as plain Markdown. */
  markus: string;
  /** The stored Markus body IR (`bodyIr`), when the read path has it. Typed by `lib/markus-ir.ts`. */
  bodyIr?: unknown;
};

/**
 * Public published stories only. Anything an anonymous visitor of the site cannot read is out of bounds: the read path is the one
 * the public site uses (the S3 projection under `siteOrigin`, or the guest `PublishedItem` queries).
 */
export interface PublicStorySource {
  /** Newest first. `limit` is the caller's: it comes from how much a spoken or on-screen list can hold. */
  listLatest(options: { limit: number }): Promise<PublicStorySummary[]>;
  /** `undefined` when no published story has that slug. */
  getStory(slug: string): Promise<PublicStory | undefined>;
}

export type VerifiedAccessToken = {
  /** The Cognito `sub`. */
  subject: string;
  claims: Record<string, unknown>;
};

export type AccessTokenResult = { ok: true; token: VerifiedAccessToken } | { ok: false; reason: string };

/** Verifies the OAuth access token Alexa sends for a linked account. */
export interface AccessTokenVerifier {
  verify(accessToken: string): Promise<AccessTokenResult>;
}

/** What every intent module may use. */
export type SkillDependencies = {
  config: AlexaConfig;
  stories: PublicStorySource;
  /** Present only when the site turned account linking on. */
  tokens?: AccessTokenVerifier;
  /** The newsroom bound to a linked editor's own access token (review/newsroom.ts). Present only with account linking. */
  review?: (accessToken: string) => import("./review/newsroom").NewsroomReview;
};

export type InteractionModelSlot = { name: string; type: string; samples?: string[] };
export type InteractionModelIntent = { name: string; slots?: InteractionModelSlot[]; samples?: string[] };
export type InteractionModelType = { name: string; values: { id?: string; name: { value: string; synonyms?: string[] } }[] };

/**
 * One intent (or request type) of the skill: the handler and what the interaction model needs to route to it. Both live in one
 * file so that adding an intent is adding a file.
 */
export type IntentModule = {
  /** Unique across the registry. By convention the file name. */
  id: string;
  create: (dependencies: SkillDependencies) => RequestHandler;
  /** Absent for a request type that is not an intent (the launch request). */
  interactionModel?: { intent: InteractionModelIntent; types?: InteractionModelType[] };
};

/** An APL document the skill can render on an Echo Show. */
export type AplDocument = {
  /** Unique across the registry; also the RenderDocument token. */
  id: string;
  /** The APL document, as the ASK package and the RenderDocument directive both take it. */
  document: Record<string, unknown> & { type: "APL" };
};

/** A step of deploy-time wiring beyond what every site with the plugin gets (IAM, a Cognito client, outputs). */
export type AlexaWiringStep = (
  backend: any,
  config: AlexaConfig,
  context: import("../types").PluginWiringContext,
  lambda: import("aws-cdk-lib/aws-lambda").Function,
) => void;

export function assertUniqueIds(kind: string, ids: readonly string[]): void {
  const seen = new Set<string>();
  for (const id of ids) {
    if (seen.has(id)) throw new Error(`Duplicate ${kind} id "${id}"`);
    seen.add(id);
  }
}
