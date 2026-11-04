import type { CreateStoryShareInput, StoryShareClient, StoryShareSummary } from "./story-share-client";

/** An in-memory stand-in for the local preview (no backend). It makes real-looking links nobody can open. */
export function createDemoStoryShareClient(now: () => Date = () => new Date()): StoryShareClient {
  const rows: Record<string, StoryShareSummary[]> = {};
  let counter = 0;
  const plus = (days: number) => new Date(now().getTime() + days * 86_400_000).toISOString().replace(/\.\d+Z$/, "Z");
  return {
    async create(input: CreateStoryShareInput) {
      counter += 1;
      const share: StoryShareSummary = {
        shareId: `demo${String(counter).padStart(8, "0")}`,
        viewers: input.viewers,
        version: input.version ?? "current",
        createdAt: now().toISOString().replace(/\.\d+Z$/, "Z"),
        createdBy: "You",
        expiresAt: plus(input.expiresInDays),
        state: "active",
        endedReason: null,
        lastOpenedOn: null,
        openCount: 0,
      };
      (rows[input.lineageId] ??= []).unshift(share);
      return { path: `/api/share/demo-preview-link-nobody-can-open-${String(counter).padStart(2, "0")}`, share };
    },
    async list(lineageId: string) {
      return [...(rows[lineageId] ?? [])];
    },
    async revoke(lineageId: string, shareId: string) {
      const row = (rows[lineageId] ?? []).find((entry) => entry.shareId === shareId);
      if (!row) throw new Error("That link was not found on this Story.");
      row.state = "revoked";
      row.endedReason = "revoked";
      return row;
    },
  };
}
