import { generateClient } from "aws-amplify/data";
import type { Schema } from "../amplify/data/resource";
import { isLocalPreviewEnabled } from "./local-preview";
import { createDemoStoryShareClient } from "./story-share-demo";

export type ShareViewers = "anyone" | "signed-in";
export const SHARE_EXPIRY_DAYS = [7, 30, 90] as const;
export type ShareExpiryDays = (typeof SHARE_EXPIRY_DAYS)[number];
export const DEFAULT_SHARE_EXPIRY_DAYS: ShareExpiryDays = 30;

export type StoryShareSummary = {
  shareId: string;
  viewers: ShareViewers;
  /** A version number, or "current" for a link that follows the Story's newest version. */
  version: number | "current";
  createdAt: string;
  createdBy: string | null;
  expiresAt: string;
  state: "active" | "expired" | "revoked" | "ended";
  endedReason: string | null;
  lastOpenedOn: string | null;
  openCount: number;
};

export type CreateStoryShareInput = { lineageId: string; viewers: ShareViewers; version?: number | null; expiresInDays: ShareExpiryDays };
export type CreatedStoryShare = { path: string; share: StoryShareSummary };

type Envelope = { data?: unknown; errors?: { message?: string }[] | null };
export type StoryShareTransport = {
  mutations: {
    createStoryShare: (args: { input: string }, options: { authMode: "userPool" }) => Promise<Envelope>;
    revokeStoryShare: (args: { input: string }, options: { authMode: "userPool" }) => Promise<Envelope>;
  };
  queries: { listStoryShares: (args: { input: string }, options: { authMode: "userPool" }) => Promise<Envelope> };
};

const USER_POOL = { authMode: "userPool" } as const;

export class StoryShareFailure extends Error {}

function answer<T>(envelope: Envelope): T {
  if (envelope.errors && envelope.errors.length > 0) throw new StoryShareFailure("The newsroom could not do that just now.");
  const raw = typeof envelope.data === "string" ? JSON.parse(envelope.data) : envelope.data;
  const value = raw as { ok?: boolean; errors?: { message?: string }[] } | null;
  if (!value || value.ok !== true) throw new StoryShareFailure(value?.errors?.map((error) => error.message).filter(Boolean).join(" ") || "The newsroom could not do that just now.");
  return value as T;
}

export function createStoryShareClient(transport: StoryShareTransport) {
  return {
    async create(input: CreateStoryShareInput): Promise<CreatedStoryShare> {
      const { version, ...rest } = input;
      return answer<CreatedStoryShare>(await transport.mutations.createStoryShare({ input: JSON.stringify({ ...rest, ...(version ? { version } : {}) }) }, USER_POOL));
    },
    async list(lineageId: string): Promise<StoryShareSummary[]> {
      return answer<{ shares: StoryShareSummary[] }>(await transport.queries.listStoryShares({ input: JSON.stringify({ lineageId }) }, USER_POOL)).shares;
    },
    async revoke(lineageId: string, shareId: string): Promise<StoryShareSummary> {
      return answer<{ share: StoryShareSummary }>(await transport.mutations.revokeStoryShare({ input: JSON.stringify({ lineageId, shareId }) }, USER_POOL)).share;
    },
  };
}

export type StoryShareClient = ReturnType<typeof createStoryShareClient>;

let defaultClient: StoryShareClient | null = null;

export function storyShareClient(): StoryShareClient {
  if (!defaultClient) {
    defaultClient = isLocalPreviewEnabled()
      ? createDemoStoryShareClient()
      : createStoryShareClient(generateClient<Schema>() as unknown as StoryShareTransport);
  }
  return defaultClient;
}

/** The address a person copies: this site's own origin and the path the function returned. */
export function shareUrl(origin: string, path: string): string {
  return `${origin.replace(/\/$/, "")}${path}`;
}

export function expiryLabel(days: number): string {
  return `${days} days`;
}

export function describeViewers(viewers: ShareViewers): string {
  return viewers === "anyone" ? "Anyone with the link" : "Signed-in editors and admins";
}

export function describeShown(version: number | "current"): string {
  return version === "current" ? "Current version, follows new versions" : `Version ${version} only`;
}

export function describeState(share: Pick<StoryShareSummary, "state" | "endedReason">): string {
  if (share.state === "active") return "Active";
  if (share.state === "expired") return "Expired";
  if (share.state === "revoked") return "Revoked";
  return share.endedReason === "published" ? "Ended: the Story was published" : share.endedReason === "spiked" ? "Ended: the Story was spiked" : "Ended";
}
