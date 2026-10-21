"use client";

import { generateClient } from "aws-amplify/data";
import type { EditorialCheckResult, EditorialFeedbackInput, EditorialFinding, RewriteResult, Span } from "./editorial-checks";
import type { EditorialChecksBackend } from "./editorial-checks-backend";
import { DEFAULT_EDITORIAL_SETTINGS, type EditorialSettings } from "./editorial-checks-settings";

export { DEFAULT_EDITORIAL_SETTINGS, type EditorialSettings };

type GraphQLResult<T> = { data?: T; errors?: { message?: string }[] };

async function call<T>(query: string, variables: Record<string, unknown> = {}): Promise<T> {
  const client = generateClient({ authMode: "userPool" });
  const result = (await client.graphql({ query, variables })) as GraphQLResult<T>;
  if (result.errors?.length) throw new Error(result.errors[0]?.message ?? "Editorial checks request failed.");
  if (!result.data) throw new Error("Editorial checks returned no data.");
  return result.data;
}

/** AWSJSON comes back as a JSON string. */
function parsed<T>(value: unknown): T {
  return (typeof value === "string" ? JSON.parse(value) : value) as T;
}

export async function checkEditorial(body: string, section: string | null): Promise<EditorialCheckResult> {
  const data = await call<{ checkEditorial: unknown }>(
    `query CheckEditorial($body: String!, $format: String, $section: String) { checkEditorial(body: $body, format: $format, section: $section) }`,
    { body, format: "markus", section },
  );
  return parsed<EditorialCheckResult>(data.checkEditorial);
}

export async function suggestRewrites(
  body: string,
  section: string | null,
  target: { finding: EditorialFinding } | { selection: Span },
  note: string | null,
): Promise<RewriteResult> {
  const data = await call<{ suggestEditorialRewrite: unknown }>(
    `query SuggestEditorialRewrite($body: String!, $format: String, $section: String, $finding: AWSJSON, $selection: AWSJSON, $note: String) {
      suggestEditorialRewrite(body: $body, format: $format, section: $section, finding: $finding, selection: $selection, note: $note)
    }`,
    {
      body,
      format: "markus",
      section,
      finding: "finding" in target ? JSON.stringify(target.finding) : null,
      selection: "selection" in target ? JSON.stringify(target.selection) : null,
      note,
    },
  );
  return parsed<RewriteResult>(data.suggestEditorialRewrite);
}

export async function recordFeedback(input: EditorialFeedbackInput): Promise<void> {
  await call(
    `mutation CreateEditorialFeedback($input: CreateEditorialFeedbackInput!) { createEditorialFeedback(input: $input) { id } }`,
    { input },
  );
}

export async function dismissedFindingIds(itemId: string): Promise<Set<string>> {
  const ids = new Set<string>();
  let nextToken: string | null | undefined;
  do {
    const data = await call<{ listEditorialFeedbackByItem: { items: { findingId: string; decision: string }[]; nextToken?: string | null } }>(
      `query ListEditorialFeedbackByItem($itemId: String!, $nextToken: String) {
        listEditorialFeedbackByItem(itemId: $itemId, limit: 500, nextToken: $nextToken) { items { findingId decision } nextToken }
      }`,
      { itemId, nextToken },
    );
    for (const item of data.listEditorialFeedbackByItem.items) if (item.decision === "dismissed") ids.add(item.findingId);
    nextToken = data.listEditorialFeedbackByItem.nextToken;
  } while (nextToken);
  return ids;
}

// --- administration ---------------------------------------------------------------

export type EditorialPolicyRecord = {
  id: string;
  policyKey: string;
  scope: string;
  version: number;
  title: string;
  guidance: string;
  severity: "info" | "warn" | "error";
  enabled: boolean;
  detectors: unknown[];
  examples: { violates?: string[]; complies?: string[] } | null;
  rewriteGuidance: string | null;
  source: string;
};

const POLICY_FIELDS = "id policyKey scope version title guidance severity enabled detectors examples rewriteGuidance source";

function policyFromRow(row: Record<string, unknown>): EditorialPolicyRecord {
  return {
    ...(row as unknown as EditorialPolicyRecord),
    detectors: parsed<unknown[]>(row.detectors ?? "[]"),
    examples: row.examples ? parsed<EditorialPolicyRecord["examples"]>(row.examples) : null,
  };
}

function policyInput(policy: EditorialPolicyRecord): Record<string, unknown> {
  return {
    ...policy,
    detectors: JSON.stringify(policy.detectors),
    examples: policy.examples ? JSON.stringify(policy.examples) : null,
  };
}

export async function listPolicies(): Promise<EditorialPolicyRecord[]> {
  const policies: EditorialPolicyRecord[] = [];
  let nextToken: string | null | undefined;
  do {
    const data = await call<{ listEditorialPolicies: { items: Record<string, unknown>[]; nextToken?: string | null } }>(
      `query ListEditorialPolicies($nextToken: String) { listEditorialPolicies(limit: 500, nextToken: $nextToken) { items { ${POLICY_FIELDS} } nextToken } }`,
      { nextToken },
    );
    policies.push(...data.listEditorialPolicies.items.map(policyFromRow));
    nextToken = data.listEditorialPolicies.nextToken;
  } while (nextToken);
  return policies.sort((a, b) => a.scope.localeCompare(b.scope) || a.title.localeCompare(b.title));
}

export async function savePolicy(policy: EditorialPolicyRecord, isNew: boolean): Promise<void> {
  const operation = isNew ? "createEditorialPolicy" : "updateEditorialPolicy";
  const inputType = isNew ? "CreateEditorialPolicyInput" : "UpdateEditorialPolicyInput";
  await call(`mutation SavePolicy($input: ${inputType}!) { ${operation}(input: $input) { id } }`, { input: policyInput(policy) });
}

export async function deletePolicy(id: string): Promise<void> {
  await call(`mutation DeleteEditorialPolicy($input: DeleteEditorialPolicyInput!) { deleteEditorialPolicy(input: $input) { id } }`, { input: { id } });
}

export async function loadSettings(): Promise<{ settings: EditorialSettings; exists: boolean }> {
  const data = await call<{ getEditorialCheckSettings: { settings: unknown } | null }>(
    `query GetEditorialCheckSettings { getEditorialCheckSettings(id: "settings") { settings } }`,
  );
  const stored = data.getEditorialCheckSettings ? parsed<Partial<EditorialSettings>>(data.getEditorialCheckSettings.settings) : {};
  return {
    settings: { ...DEFAULT_EDITORIAL_SETTINGS, ...stored, lanes: { ...DEFAULT_EDITORIAL_SETTINGS.lanes, ...(stored.lanes ?? {}) } },
    exists: data.getEditorialCheckSettings !== null,
  };
}

export async function saveSettings(settings: EditorialSettings, exists: boolean): Promise<void> {
  const operation = exists ? "updateEditorialCheckSettings" : "createEditorialCheckSettings";
  const inputType = exists ? "UpdateEditorialCheckSettingsInput" : "CreateEditorialCheckSettingsInput";
  await call(`mutation SaveSettings($input: ${inputType}!) { ${operation}(input: $input) { id } }`, {
    input: { id: "settings", settings: JSON.stringify(settings) },
  });
}

export async function importStarterPack(name: string): Promise<{ created: number; skipped: number }> {
  const data = await call<{ importEditorialStarterPack: unknown }>(
    `mutation ImportStarterPack($name: String!) { importEditorialStarterPack(name: $name) }`,
    { name },
  );
  return parsed(data.importEditorialStarterPack);
}

export type StarterPackSummary = {
  name: string;
  title: string;
  version?: string | null;
  language?: string | null;
  guidance?: string | null;
  policyCount: number;
  importedCount: number;
  isDefault: boolean;
  policies: { id: string; title?: string | null; severity?: string | null; tags: string[]; lanes: string[] }[];
};

/** The starter packs the site's Humanus ships, with how many of each pack's policies the site already has. */
export async function listStarterPacks(): Promise<{ humanusVersion?: string | null; packs: StarterPackSummary[] }> {
  const data = await call<{ listEditorialStarterPacks: unknown }>(`query ListStarterPacks { listEditorialStarterPacks }`);
  return parsed(data.listEditorialStarterPacks);
}

export async function tryPolicy(policy: Record<string, unknown>, text: string): Promise<EditorialCheckResult> {
  const data = await call<{ tryEditorialPolicy: unknown }>(
    `query TryEditorialPolicy($policy: AWSJSON!, $text: String!) { tryEditorialPolicy(policy: $policy, text: $text, format: "markus") }`,
    { policy: JSON.stringify(policy), text },
  );
  return parsed(data.tryEditorialPolicy);
}

export type DraftedQuestions = { detectors: Record<string, unknown>[]; notes: string[]; model: string };

export async function draftQuestions(title: string, guidance: string): Promise<DraftedQuestions> {
  const data = await call<{ draftEditorialQuestions: unknown }>(
    `query DraftEditorialQuestions($title: String!, $guidance: String!) { draftEditorialQuestions(title: $title, guidance: $guidance) }`,
    { title, guidance },
  );
  return parsed(data.draftEditorialQuestions);
}

export async function recalibrate(): Promise<{ updated: number; detectors: { policyId: string; detectorId: string; labels: number; note?: string }[] }> {
  const data = await call<{ recalibrateEditorialPolicies: unknown }>(`mutation Recalibrate { recalibrateEditorialPolicies }`);
  return parsed(data.recalibrateEditorialPolicies);
}

/** The site's GraphQL API, signed in as the editor. */
export const graphqlEditorialBackend: EditorialChecksBackend = {
  loadSettings,
  dismissedFindingIds,
  check: checkEditorial,
  suggest: suggestRewrites,
  recordFeedback,
};
