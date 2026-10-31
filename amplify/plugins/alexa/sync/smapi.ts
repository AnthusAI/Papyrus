/**
 * The Skill Management API (SMAPI) over plain HTTPS, with a Login with Amazon (LWA) access token. No ASK CLI. Every call goes
 * through an injected `fetch`, so tests run against a fake and make no network call.
 */
export const LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token";
export const SMAPI_BASE_URL = "https://api.amazonalexa.com";
const STAGE = "development";

export type LwaCredentials = { clientId: string; clientSecret: string; refreshToken: string };

/** What the sync needs from Amazon. Each method returns once Amazon has finished the work it started (or throws). */
export interface SmapiClient {
  /** `POST /v1/skills`: returns the new skill's ID. */
  createSkill(vendorId: string, manifest: unknown): Promise<string>;
  /** `PUT /v1/skills/{id}/stages/development/manifest`. */
  updateManifest(skillId: string, manifest: unknown): Promise<void>;
  /** `PUT .../interactionModel/locales/{locale}`. Amazon builds the model as part of accepting it; this waits for the build. */
  putInteractionModel(skillId: string, locale: string, model: unknown): Promise<void>;
  /** `PUT .../accountLinkingClient`. */
  putAccountLinking(skillId: string, request: unknown): Promise<void>;
}

export class SmapiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export type SmapiOptions = {
  fetch?: typeof fetch;
  sleep?: (milliseconds: number) => Promise<void>;
  /** Poll interval for the asynchronous updates (default 3 seconds). */
  pollIntervalMs?: number;
  /** Give up waiting for one update after this long (default 10 minutes). */
  timeoutMs?: number;
};

type Json = Record<string, any>;

export async function fetchLwaAccessToken(credentials: LwaCredentials, fetchImpl: typeof fetch = fetch): Promise<string> {
  const response = await fetchImpl(LWA_TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: credentials.refreshToken,
      client_id: credentials.clientId,
      client_secret: credentials.clientSecret,
    }).toString(),
  });
  const body = (await response.json().catch(() => ({}))) as Json;
  if (!response.ok || typeof body.access_token !== "string") {
    throw new SmapiError(`Login with Amazon refused the refresh token (${response.status}${body.error ? ` ${body.error}` : ""})`, response.status);
  }
  return body.access_token;
}

export function createSmapiClient(accessToken: string, options: SmapiOptions = {}): SmapiClient {
  const fetchImpl = options.fetch ?? fetch;
  const sleep = options.sleep ?? ((milliseconds: number) => new Promise<void>((resolve) => setTimeout(resolve, milliseconds)));
  const pollIntervalMs = options.pollIntervalMs ?? 3_000;
  const timeoutMs = options.timeoutMs ?? 600_000;

  async function call(method: string, path: string, body?: unknown): Promise<{ status: number; body: Json }> {
    const response = await fetchImpl(`${SMAPI_BASE_URL}${path}`, {
      method,
      headers: { authorization: `Bearer ${accessToken}`, ...(body === undefined ? {} : { "content-type": "application/json" }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await response.text();
    let parsed: Json = {};
    try {
      parsed = text === "" ? {} : (JSON.parse(text) as Json);
    } catch {
      parsed = { message: text };
    }
    if (!response.ok) {
      throw new SmapiError(`SMAPI ${method} ${path} failed (${response.status}): ${parsed.message ?? text.slice(0, 300)}`, response.status);
    }
    return { status: response.status, body: parsed };
  }

  /** Waits until `pick(status)` says SUCCEEDED; FAILED throws with Amazon's error messages. */
  async function waitFor(skillId: string, resource: string, pick: (status: Json) => Json | undefined): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const { body } = await call("GET", `/v1/skills/${skillId}/status?resource=${resource}`);
      const update = pick(body)?.lastUpdateRequest as Json | undefined;
      if (update?.status === "SUCCEEDED") return;
      if (update?.status === "FAILED") {
        const reasons = (update.errors as Json[] | undefined)?.map((error) => error.message).filter(Boolean).join("; ");
        throw new SmapiError(`Amazon rejected the ${resource}${reasons ? `: ${reasons}` : ""}`, 422);
      }
      if (Date.now() >= deadline) throw new SmapiError(`Amazon did not finish the ${resource} update in time`, 504);
      await sleep(pollIntervalMs);
    }
  }

  return {
    async createSkill(vendorId, manifest) {
      const { body } = await call("POST", "/v1/skills", { vendorId, ...(manifest as Json) });
      const skillId = body.skillId;
      if (typeof skillId !== "string") throw new SmapiError("SMAPI did not return a skill ID", 502);
      await waitFor(skillId, "manifest", (status) => status.manifest);
      return skillId;
    },
    async updateManifest(skillId, manifest) {
      await call("PUT", `/v1/skills/${skillId}/stages/${STAGE}/manifest`, manifest);
      await waitFor(skillId, "manifest", (status) => status.manifest);
    },
    async putInteractionModel(skillId, locale, model) {
      await call("PUT", `/v1/skills/${skillId}/stages/${STAGE}/interactionModel/locales/${locale}`, model);
      await waitFor(skillId, "interactionModel", (status) => status.interactionModel?.[locale]);
    },
    async putAccountLinking(skillId, request) {
      await call("PUT", `/v1/skills/${skillId}/stages/${STAGE}/accountLinkingClient`, request);
    },
  };
}
