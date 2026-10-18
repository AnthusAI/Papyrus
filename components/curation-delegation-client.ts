"use client";

import { generateClient } from "aws-amplify/data";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import type { CurationDelegationRecord } from "../lib/curation-delegation-helpers";
import { configureAmplifyClient } from "./amplify-client-provider";

const USER_POOL_AUTH_MODE = "userPool";

export type CreatedCurationDelegation = CurationDelegationRecord & { token: string };

const CREATE_MUTATION = `
  mutation CreateCurationDelegation($agentLabel: String!, $hours: Int) {
    createCurationDelegation(agentLabel: $agentLabel, hours: $hours) {
      delegationId token agentLabel grantorLabel expiresAt revokedAt
    }
  }
`;

const REVOKE_MUTATION = `
  mutation RevokeCurationDelegation($delegationId: ID!) {
    revokeCurationDelegation(delegationId: $delegationId) {
      delegationId agentLabel grantorLabel expiresAt revokedAt
    }
  }
`;

const LIST_QUERY = `
  query ListCurationDelegations {
    listCurationDelegations {
      delegationId agentLabel grantorLabel expiresAt revokedAt
    }
  }
`;

const previewDelegations: CurationDelegationRecord[] = [];

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

export async function createCurationDelegation(agentLabel: string, hours: number): Promise<CreatedCurationDelegation> {
  if (isLocalPreviewEnabled()) {
    const delegationId = `curation-delegation-preview-${previewDelegations.length + 1}`;
    const record: CurationDelegationRecord = {
      delegationId,
      agentLabel,
      grantorLabel: "ryan@example.com",
      expiresAt: new Date(Date.now() + hours * 3_600_000).toISOString(),
      revokedAt: null,
    };
    previewDelegations.push(record);
    return { ...record, token: `${delegationId}~preview-token-not-valid-anywhere` };
  }
  const data = await runGraphql<{ createCurationDelegation: CreatedCurationDelegation }>(CREATE_MUTATION, { agentLabel, hours });
  return data.createCurationDelegation;
}

export async function revokeCurationDelegation(delegationId: string): Promise<CurationDelegationRecord> {
  if (isLocalPreviewEnabled()) {
    const record = previewDelegations.find((entry) => entry.delegationId === delegationId);
    if (!record) throw new Error("That delegation was not found.");
    record.revokedAt = record.revokedAt ?? new Date().toISOString();
    return { ...record };
  }
  const data = await runGraphql<{ revokeCurationDelegation: CurationDelegationRecord }>(REVOKE_MUTATION, { delegationId });
  return data.revokeCurationDelegation;
}

export async function listCurationDelegations(): Promise<CurationDelegationRecord[]> {
  if (isLocalPreviewEnabled()) return previewDelegations.map((entry) => ({ ...entry })).reverse();
  const data = await runGraphql<{ listCurationDelegations: CurationDelegationRecord[] }>(LIST_QUERY, {});
  return data.listCurationDelegations ?? [];
}
