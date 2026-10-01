import { createHash, randomUUID } from "node:crypto";
import { getAmplifyDataClientConfig } from "@aws-amplify/backend/function/runtime";
import { Amplify } from "aws-amplify";
import { generateClient } from "aws-amplify/data";
import type { Schema } from "../../data/resource";

type GetSettingsHandler = Schema["getReaderSettings"]["functionHandler"];
type UpdateSettingsHandler = Schema["updateReaderSettings"]["functionHandler"];
type ReaderSettingsEvent = Parameters<GetSettingsHandler>[0] | Parameters<UpdateSettingsHandler>[0];
type DataClient = ReturnType<typeof generateClient<Schema>>;
type DataClientErrors = Array<{ message?: string | null } | string | null> | null | undefined;
type DataClientResult<T = unknown> = {
  data?: T | null;
  errors?: DataClientErrors;
  nextToken?: string | null;
};

type ReaderSettings = {
  presentation: "newsprint" | "blog" | "magazine";
  theme: "system" | "light" | "dark";
};

type UserProfileRecord = {
  id: string;
  email?: string | null;
  displayName?: string | null;
  settings?: unknown;
  status?: string | null;
  mergedIntoProfileId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

type UserIdentityRecord = {
  id: string;
  userProfileId: string;
  cognitoSub: string;
  provider?: string | null;
  email?: string | null;
  status: string;
  linkedAt: string;
  lastSeenAt?: string | null;
};

const ACTIVE_IDENTITY_STATUS = "active";
const DEFAULT_SETTINGS: ReaderSettings = {
  presentation: "newsprint",
  theme: "system",
};

let clientPromise: Promise<DataClient> | null = null;

export const handler = async (event: ReaderSettingsEvent) => {
  const client = await getDataClient();
  const operation = getOperationName(event);
  const identity = readRequiredIdentity(event);
  const profile = await resolveReaderProfile(client, identity);

  if (operation === "getReaderSettings") {
    return {
      userProfileId: profile.id,
      email: profile.email ?? null,
      settings: hasStoredReaderSettings(profile.settings) ? normalizeReaderSettings(profile.settings) : null,
      avatarHash: computeAvatarHash(profile.email),
    };
  }

  if (operation === "updateReaderSettings") {
    if (!("settings" in event.arguments)) throw new Error("settings is required.");
    const nextSettings = normalizeReaderSettings(event.arguments.settings);
    const now = new Date().toISOString();
    await requireDataResult(
      client.models.UserProfile.update({
        id: profile.id,
        settings: nextSettings,
        updatedAt: now,
      }),
      "update UserProfile reader settings",
    );
    return {
      userProfileId: profile.id,
      email: profile.email ?? null,
      settings: nextSettings,
      avatarHash: computeAvatarHash(profile.email),
    };
  }

  throw new Error(`Unsupported reader settings operation ${operation}.`);
};

function getOperationName(event: ReaderSettingsEvent): string {
  const operation = normalizeOptionalString(event.info?.fieldName) ?? normalizeOptionalString((event as { fieldName?: string | null }).fieldName);
  if (!operation) throw new Error("Reader settings operation event did not include a field name.");
  return operation;
}

async function resolveReaderProfile(
  client: DataClient,
  identity: {
    sub: string;
    email?: string | null;
    displayName?: string | null;
    provider?: string | null;
  },
): Promise<UserProfileRecord> {
  const now = new Date().toISOString();
  const identities = await listDataRecords<UserIdentityRecord>(client.models.UserIdentity);
  const existingIdentity = identities.find((record) => (
    record.cognitoSub === identity.sub && record.status === ACTIVE_IDENTITY_STATUS
  ));

  if (existingIdentity) {
    await requireDataResult(
      client.models.UserIdentity.update({
        id: existingIdentity.id,
        lastSeenAt: now,
      }),
      "update UserIdentity lastSeenAt",
    );
    let profile = await getDataRecord<UserProfileRecord>(client.models.UserProfile, existingIdentity.userProfileId, "get UserProfile");
    if (!profile) throw new Error(`UserProfile ${existingIdentity.userProfileId} was not found.`);
    if (profile.mergedIntoProfileId) {
      const mergedTarget = await getDataRecord<UserProfileRecord>(client.models.UserProfile, profile.mergedIntoProfileId, "get merged UserProfile");
      if (mergedTarget) return mergedTarget;
    }
    const nextEmail = identity.email ?? null;
    const currentEmail = normalizeOptionalString(profile.email);
    if (nextEmail && nextEmail !== currentEmail) {
      profile = await requireDataResult(
        client.models.UserProfile.update({
          id: profile.id,
          email: nextEmail,
          updatedAt: now,
        }),
        "update UserProfile email",
      );
    }
    return profile;
  }

  const profileId = `user-profile-${safeId(identity.sub)}`;
  const existingProfile = await getDataRecord<UserProfileRecord>(client.models.UserProfile, profileId, "get UserProfile");
  const profile = existingProfile
    ? await maybeRefreshProfileFromIdentity(client, existingProfile, identity, now)
    : await requireDataResult(
      client.models.UserProfile.create({
        id: profileId,
        email: identity.email ?? null,
        displayName: identity.displayName ?? identity.email ?? "Papyrus reader",
        status: ACTIVE_IDENTITY_STATUS,
        createdAt: now,
        updatedAt: now,
      }),
      "create UserProfile",
    );

  await requireDataResult(
    client.models.UserIdentity.create({
      id: `user-identity-${safeId(identity.sub)}-${randomUUID().slice(0, 8)}`,
      userProfileId: profileId,
      cognitoSub: identity.sub,
      provider: identity.provider ?? null,
      email: identity.email ?? null,
      status: ACTIVE_IDENTITY_STATUS,
      linkedAt: now,
      lastSeenAt: now,
    }),
    "create UserIdentity",
  );

  return profile;
}

async function maybeRefreshProfileFromIdentity(
  client: DataClient,
  profile: UserProfileRecord,
  identity: {
    sub: string;
    email?: string | null;
    displayName?: string | null;
    provider?: string | null;
  },
  now: string,
): Promise<UserProfileRecord> {
  const currentEmail = normalizeOptionalString(profile.email);
  const nextEmail = normalizeOptionalString(identity.email);
  const nextDisplayName = normalizeOptionalString(identity.displayName);
  const patch: {
    id: string;
    email?: string | null;
    displayName?: string | null;
    updatedAt: string;
  } = {
    id: profile.id,
    updatedAt: now,
  };
  let changed = false;
  if (nextEmail && nextEmail !== currentEmail) {
    patch.email = nextEmail;
    changed = true;
  }
  if (nextDisplayName && nextDisplayName !== normalizeOptionalString(profile.displayName)) {
    patch.displayName = nextDisplayName;
    changed = true;
  }
  if (!changed) return profile;
  return requireDataResult(
    client.models.UserProfile.update(patch),
    "refresh UserProfile identity fields",
  );
}

function normalizeReaderSettings(value: unknown): ReaderSettings {
  const candidate = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    presentation: normalizePresentation(candidate.presentation),
    theme: normalizeTheme(candidate.theme),
  };
}

function hasStoredReaderSettings(value: unknown): boolean {
  return Boolean(value && typeof value === "object");
}

function normalizePresentation(value: unknown): ReaderSettings["presentation"] {
  if (value === "blog" || value === "magazine" || value === "newsprint") return value;
  // Handle deprecated "newspaper" value as an alias for "newsprint"
  if (value === "newspaper") return "newsprint";
  return DEFAULT_SETTINGS.presentation;
}

function normalizeTheme(value: unknown): ReaderSettings["theme"] {
  return value === "light" || value === "dark" || value === "system" ? value : DEFAULT_SETTINGS.theme;
}

function computeAvatarHash(email: string | null | undefined): string | null {
  const normalized = normalizeOptionalString(email)?.toLowerCase();
  if (!normalized) return null;
  return createHash("md5").update(normalized).digest("hex");
}

function readRequiredIdentity(event: ReaderSettingsEvent): {
  sub: string;
  email?: string | null;
  displayName?: string | null;
  provider?: string | null;
} {
  const identity = event.identity as { sub?: unknown; username?: unknown; claims?: Record<string, unknown> } | null | undefined;
  const claims = identity?.claims ?? {};
  const sub = normalizeOptionalString(identity?.sub) ?? normalizeOptionalString(claims.sub);
  if (!sub) throw new Error("Reader settings require an authenticated Cognito user.");
  return {
    sub,
    email: normalizeOptionalString(claims.email),
    displayName: normalizeOptionalString(claims.name) ?? normalizeOptionalString(claims["cognito:username"]) ?? normalizeOptionalString(identity?.username),
    provider: normalizeProvider(claims.identities),
  };
}

function normalizeProvider(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  const first = value.find((entry) => entry && typeof entry === "object") as Record<string, unknown> | undefined;
  return normalizeOptionalString(first?.providerName);
}

async function getDataClient(): Promise<DataClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const { resourceConfig, libraryOptions } = await getAmplifyDataClientConfig(process.env as never);
      Amplify.configure(resourceConfig, libraryOptions);
      return generateClient<Schema>();
    })();
  }
  return clientPromise;
}

async function listDataRecords<T>(model: { list(input?: Record<string, unknown>): Promise<DataClientResult<T[]>> }): Promise<T[]> {
  const records: T[] = [];
  let nextToken: string | null | undefined;
  do {
    const page = await model.list({ limit: 100, nextToken });
    assertNoDataErrors(page.errors, "list records");
    records.push(...((page.data ?? []).filter(Boolean) as T[]));
    nextToken = page.nextToken;
  } while (nextToken);
  return records;
}

async function getDataRecord<T>(
  model: { get(input: { id: string }): Promise<DataClientResult<T>> },
  id: string,
  operation: string,
): Promise<T | null> {
  const response = await model.get({ id });
  assertNoDataErrors(response.errors, operation);
  return response.data ?? null;
}

async function requireDataResult<T>(promise: Promise<DataClientResult<T>>, operation: string): Promise<T> {
  const response = await promise;
  assertNoDataErrors(response.errors, operation);
  if (!response.data) throw new Error(`${operation} returned no data.`);
  return response.data;
}

function assertNoDataErrors(errors: DataClientErrors, operation: string): void {
  if (!errors?.length) return;
  throw new Error(`${operation} failed: ${errors.map(formatDataError).join("; ")}`);
}

function formatDataError(error: { message?: string | null } | string | null): string {
  if (typeof error === "string") return error;
  return error?.message ?? "GraphQL data operation failed.";
}

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function safeId(value: string): string {
  return createHash("sha256").update(value).digest("hex").slice(0, 32);
}
