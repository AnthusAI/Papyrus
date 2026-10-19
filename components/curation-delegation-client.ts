"use client";

import { generateClient } from "aws-amplify/data";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import type { CurationDelegationRecord } from "../lib/curation-delegation-helpers";
import { configureAmplifyClient } from "./amplify-client-provider";

const USER_POOL_AUTH_MODE = "userPool";

const DELEGATION_FIELDS = "delegationId agentLabel grantorLabel expiresAt revokedAt state userCode requestedHours pendingExpiresAt approvedAt deniedAt";

const APPROVE_MUTATION = `
  mutation ApproveCurationDelegation($userCode: String!) {
    approveCurationDelegation(userCode: $userCode) { ${DELEGATION_FIELDS} }
  }
`;

const DENY_MUTATION = `
  mutation DenyCurationDelegation($userCode: String!) {
    denyCurationDelegation(userCode: $userCode) { ${DELEGATION_FIELDS} }
  }
`;

const REVOKE_MUTATION = `
  mutation RevokeCurationDelegation($delegationId: ID!) {
    revokeCurationDelegation(delegationId: $delegationId) {
      ${DELEGATION_FIELDS}
    }
  }
`;

const LIST_QUERY = `
  query ListCurationDelegations {
    listCurationDelegations {
      ${DELEGATION_FIELDS}
    }
  }
`;

function previewPendingRequest(agentLabel: string, userCode: string, requestedHours: number, minutesLeft: number, id: string): CurationDelegationRecord {
  const pendingExpiresAt = new Date(Date.now() + minutesLeft * 60_000).toISOString();
  return { delegationId: id, agentLabel, grantorLabel: null, expiresAt: pendingExpiresAt, revokedAt: null, state: "pending", userCode, requestedHours, pendingExpiresAt, approvedAt: null, deniedAt: null };
}

const previewDelegations: CurationDelegationRecord[] = [
  previewPendingRequest("e2e-check", "WDJB-MJHT", 1, 9.5, "curation-delegation-preview-pending-1"),
  previewPendingRequest("section-curator", "KQPR-4XNZ", 8, 4, "curation-delegation-preview-pending-2"),
];

function normalizedCode(code: string): string {
  return code.replace(/[^a-z0-9]/gi, "").toUpperCase();
}

async function runGraphql<T>(query: string, variables: Record<string, unknown>): Promise<T> {
  configureAmplifyClient();
  const client = generateClient() as unknown as {
    graphql: (options: Record<string, unknown>) => Promise<{ data?: T | null; errors?: Array<{ message?: string }> | null }>;
  };
  const response = await client.graphql({ query, variables, authMode: USER_POOL_AUTH_MODE });
  if (response.errors?.length) throw Object.assign(new Error(response.errors[0]?.message ?? "Request failed."), { errors: response.errors });
  if (!response.data) throw new Error("The server returned no result.");
  return response.data;
}

export async function approveCurationDelegation(userCode: string): Promise<CurationDelegationRecord> {
  if (isLocalPreviewEnabled()) {
    const record = previewDelegations.find((entry) => entry.state === "pending" && normalizedCode(entry.userCode ?? "") === normalizedCode(userCode));
    if (!record) throw new Error("That code was not found, has expired, or was already decided.");
    const now = Date.now();
    Object.assign(record, { state: "approved", userCode: null, grantorLabel: "ryan@example.com", approvedAt: new Date(now).toISOString(), expiresAt: new Date(now + (record.requestedHours ?? 1) * 3_600_000).toISOString() });
    return { ...record };
  }
  const data = await runGraphql<{ approveCurationDelegation: CurationDelegationRecord }>(APPROVE_MUTATION, { userCode });
  return data.approveCurationDelegation;
}

export async function denyCurationDelegation(userCode: string): Promise<CurationDelegationRecord> {
  if (isLocalPreviewEnabled()) {
    const record = previewDelegations.find((entry) => entry.state === "pending" && normalizedCode(entry.userCode ?? "") === normalizedCode(userCode));
    if (!record) throw new Error("That code was not found, has expired, or was already decided.");
    Object.assign(record, { state: "denied", userCode: null, deniedAt: new Date().toISOString() });
    return { ...record };
  }
  const data = await runGraphql<{ denyCurationDelegation: CurationDelegationRecord }>(DENY_MUTATION, { userCode });
  return data.denyCurationDelegation;
}

export async function revokeCurationDelegation(delegationId: string): Promise<CurationDelegationRecord> {
  if (isLocalPreviewEnabled()) {
    const record = previewDelegations.find((entry) => entry.delegationId === delegationId);
    if (!record) throw new Error("That delegation was not found.");
    record.revokedAt = record.revokedAt ?? new Date().toISOString();
    record.state = "revoked";
    return { ...record };
  }
  const data = await runGraphql<{ revokeCurationDelegation: CurationDelegationRecord }>(REVOKE_MUTATION, { delegationId });
  return data.revokeCurationDelegation;
}

export async function listCurationDelegations(): Promise<CurationDelegationRecord[]> {
  if (isLocalPreviewEnabled()) return previewDelegations.map((entry) => ({ ...entry }));
  const data = await runGraphql<{ listCurationDelegations: CurationDelegationRecord[] }>(LIST_QUERY, {});
  return data.listCurationDelegations ?? [];
}
