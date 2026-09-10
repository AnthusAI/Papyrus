"use client";

import "aws-amplify/auth/enable-oauth-listener";
import { fetchAuthSession } from "aws-amplify/auth";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { Amplify, type ResourcesConfig } from "aws-amplify";
import { CookieStorage, Hub } from "aws-amplify/utils";
import { useEffect } from "react";
import { assertSandboxAmplifyOutputsForDev } from "../lib/amplify-outputs-guard";
import amplifyOutputs from "../amplify_outputs.json";

let configured = false;

export function configureAmplifyClient() {
  if (configured) return;
  assertSandboxAmplifyOutputsForDev(amplifyOutputs as Record<string, unknown>);
  Amplify.configure(prioritizeCurrentOrigin(amplifyOutputs as ResourcesConfig), { ssr: true });
  applyClientTokenStorageForCurrentProtocol();
  configured = true;
  redirectLoopbackToLocalhost();
}

export function AmplifyClientProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  useEffect(() => {
    configureAmplifyClient();
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      if (payload.event !== "signInWithRedirect_failure") return;
      const detail = extractAuthFailureDetail(payload.data);
      if (detail) {
        console.error("[PapyrusAuth] Google sign-in failed:", detail);
      }
    });

    const params = new URLSearchParams(window.location.search);
    const hasOAuthCallback = params.has("code") && params.has("state");
    const hasOAuthError = params.has("error");
    if (!hasOAuthCallback && !hasOAuthError) {
      return unsubscribe;
    }

    let cancelled = false;
    const syncSession = async () => {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        if (cancelled) return;
        try {
          const session = await fetchAuthSession({ forceRefresh: attempt > 0 });
          if (session.tokens?.accessToken) return;
        } catch {
          // OAuth listener may still be completing the code exchange.
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    };
    void syncSession();

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  configureAmplifyClient();
  return children;
}

if (typeof window !== "undefined") {
  configureAmplifyClient();
}

function prioritizeCurrentOrigin(config: ResourcesConfig): ResourcesConfig {
  if (typeof window === "undefined") return config;
  const auth = (config as { auth?: { oauth?: Record<string, unknown> } }).auth;
  const oauth = auth?.oauth;
  if (!auth || !oauth) return config;
  const origin = normalizeUrlOrigin(window.location.origin);
  const reorder = (urls: unknown) => {
    if (!Array.isArray(urls)) return urls;
    const normalized = urls.filter((value): value is string => typeof value === "string");
    const head = normalized.filter((value) => normalizeUrlOrigin(value) === origin);
    if (!head.length) return normalized;
    const tail = normalized.filter((value) => normalizeUrlOrigin(value) !== origin);
    return [...head, ...tail];
  };
  return {
    ...config,
    auth: {
      ...auth,
      oauth: {
        ...oauth,
        redirect_sign_in_uri: reorder(oauth.redirect_sign_in_uri),
        redirect_sign_out_uri: reorder(oauth.redirect_sign_out_uri),
      },
    },
  } as ResourcesConfig;
}

function applyClientTokenStorageForCurrentProtocol(): void {
  if (typeof window === "undefined") return;
  if (window.location.protocol !== "http:") return;
  // Amplify's default SSR cookie store sets secure cookies, which browsers reject on http://localhost.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(
    new CookieStorage({ sameSite: "lax", secure: false }),
  );
}

function redirectLoopbackToLocalhost(): void {
  if (typeof window === "undefined") return;
  const { protocol, hostname, port, pathname, search, hash } = window.location;
  if (hostname !== "127.0.0.1" && hostname !== "::1") return;
  const target = `${protocol}//localhost${port ? `:${port}` : ""}${pathname}${search}${hash}`;
  window.location.replace(target);
}

function normalizeUrlOrigin(value: string): string {
  const trimmed = value.replace(/\/+$/, "");
  try {
    const parsed = new URL(trimmed);
    const hostname = normalizeLoopbackHostname(parsed.hostname);
    return `${parsed.protocol}//${hostname}${parsed.port ? `:${parsed.port}` : ""}`;
  } catch {
    return trimmed;
  }
}

function normalizeLoopbackHostname(hostname: string): string {
  if (hostname === "127.0.0.1" || hostname === "::1") return "localhost";
  return hostname;
}

function extractAuthFailureDetail(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === "string") return error;
  if (typeof error !== "object") return null;
  const record = error as Record<string, unknown>;
  const message = record.message;
  if (typeof message === "string" && message.trim()) return message;
  const nested = record.error;
  if (nested && nested !== error) return extractAuthFailureDetail(nested);
  return null;
}
