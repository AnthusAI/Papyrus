import React from "react";
import { createRoot } from "react-dom/client";
import { NewsroomCurationProvider } from "../../components/newsroom-curation-provider";
import { NewsroomReferencesView } from "../../components/newsroom-references-view";
import type { CurationBootstrap, CurationRequest } from "../../lib/curation-client";
import { DEMO_CYCLOTRON_STATUS } from "../../lib/relevance-status";

/** A browser fixture with an in-memory curation transport; no network, no credentials. */
const scope = { accountId: "account-a", publicationId: "publication-a", bindingRevision: "binding-1" };
const bootstrap: CurationBootstrap = {
  scope, mode: "embedded", bindingRef: null, capabilities: ["read", "review"],
  priming: { listId: "examples", classifiers: [{ id: "relevant", revision: 1 }] },
};
const outputs = [{ id: "relevant", question: "Relevant to this publication?", classes: ["include", "exclude"], positiveLabel: "include" }];
const envelope = { ...scope, contractVersion: "cyclotron-publication/v1", outputs };
const contract = {
  list_id: "examples", schema: {}, transformers: [],
  classifiers: [{ id: "relevant", revision: 1, name: "Relevant", config: { question: "Relevant?", classes: [{ label: "include" }, { label: "exclude" }] } }],
};
const draft = (status: string) => ({
  id: "draft-1", version: 1, status, contract, source: { kind: "file" }, errors: [], fields: [],
  rows: [{ row: 1, item: { id: "item-1", values: { title: "Imported paper", abstract: "An abstract.", source_uri: "https://example.test/p" } },
    labels: {}, model_representation: { relevant: { title: "Imported paper" } } }],
});
const imported = {
  decision: { decisionId: "d-1", itemId: "item-1", createdAt: "2026-10-20T00:00:00Z",
    classifiers: { relevant: { label: "include", confidence: 0.8, probabilities: { include: 0.8, exclude: 0.2 }, version: 1, fingerprint: "f" } },
    review: { selected: false, reason: null, propensity: 1, detail: "" } },
  item: { title: "Newly added reference" }, reviews: {},
};

// Stable props: the view re-renders forever if its list defaults are recreated each render.
const NONE: never[] = [];

const state = { added: false, snapshots: 0 };
(window as unknown as { __fixture: typeof state }).__fixture = state;

const request: CurationRequest = async <T,>(path: string, body: Record<string, unknown>) => {
  if (path.endsWith("/publication")) {
    if (body.operation === "status") state.snapshots += 1;
    const status = { ...envelope, classifiers: { relevant: DEMO_CYCLOTRON_STATUS } };
    return (body.operation === "status" ? status : { ...envelope, history: state.added ? [imported] : [] }) as T;
  }
  const query = String(body.query);
  const action = (body.variables as { action?: string })?.action;
  if (query.includes("primingContract")) return { data: { primingContract: contract } } as T;
  if (action === "accept") { state.added = true; return { data: { primingCommand: draft("accepted") } } as T; }
  if (action === "cancel") return { data: { primingCommand: draft("cancelled") } } as T;
  return { data: { primingCommand: draft("preview") } } as T;
};

createRoot(document.getElementById("root")!).render(
  <NewsroomCurationProvider bootstrap={bootstrap} request={request}>
    <NewsroomReferencesView onReview={() => undefined} references={NONE} sections={NONE} referenceAttachments={NONE}
      cyclotronPriming={{ labels: ["include", "exclude"], requests: [], onRequest: () => undefined }} />
  </NewsroomCurationProvider>,
);
