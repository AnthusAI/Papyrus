"use client";

import { signInWithRedirect, signOut } from "aws-amplify/auth";
import { Hub } from "aws-amplify/utils";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { configureAmplifyClient } from "./amplify-client-provider";
import { loadReaderSessionSnapshot, type ReaderAuthSnapshot } from "./reader-auth-state";

type ReaderAuthControlProps = {
  className?: string;
  dataFooterUtility?: string;
  postAuthPath?: string;
  showIdentity?: boolean;
  authState?: ReaderAuthSnapshot;
  renderAction?: (action: { disabled: boolean; onClick: () => void; signedIn: boolean }) => ReactNode;
};

const POST_AUTH_PATH_KEY = "papyrus:reader-auth:post-auth-path";

export function ReaderAuthControl({
  className,
  dataFooterUtility,
  postAuthPath,
  showIdentity = false,
  authState: externalAuthState,
  renderAction,
}: ReaderAuthControlProps) {
  const [authState, setAuthState] = useState<ReaderAuthSnapshot>(externalAuthState ?? { status: "loading", label: "Checking sign-in" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isExternallyManaged = Boolean(externalAuthState);

  const replaceWithPostAuthPath = useCallback(() => {
    const storedPath = typeof window === "undefined" ? null : window.sessionStorage.getItem(POST_AUTH_PATH_KEY);
    const nextPath = postAuthPath ?? storedPath;
    if (!nextPath) return;
    if (window.location.pathname !== "/" || window.location.search || window.location.hash) return;
    if (storedPath) window.sessionStorage.removeItem(POST_AUTH_PATH_KEY);
    window.history.replaceState(window.history.state, "", nextPath);
  }, [postAuthPath]);

  const refreshAuthState = useCallback(async () => {
    const snapshot = await loadReaderSessionSnapshot();
    setAuthState(snapshot.auth);
    setError(null);
    if (snapshot.auth.status === "signedIn") replaceWithPostAuthPath();
  }, [replaceWithPostAuthPath]);

  useEffect(() => {
    if (externalAuthState) {
      setAuthState(externalAuthState);
      setBusy(false);
      return;
    }

    let active = true;

    const refreshIfActive = async () => {
      await refreshAuthState();
      if (!active) return;
      setBusy(false);
    };

    void refreshIfActive();
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      if (
        payload.event === "signedIn" ||
        payload.event === "signedOut" ||
        payload.event === "signInWithRedirect" ||
        payload.event === "signInWithRedirect_failure"
      ) {
        void refreshIfActive();
      }
      if (payload.event === "signInWithRedirect_failure") {
        setError(formatAuthFailure(payload.data));
      }
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [externalAuthState, refreshAuthState]);

  const signIn = async () => {
    configureAmplifyClient();
    setBusy(true);
    setError(null);
    try {
      if (typeof window !== "undefined") {
        const intendedPath = postAuthPath ?? `${window.location.pathname}${window.location.search}${window.location.hash}`;
        if (intendedPath && intendedPath !== "/") {
          window.sessionStorage.setItem(POST_AUTH_PATH_KEY, intendedPath);
        } else {
          window.sessionStorage.removeItem(POST_AUTH_PATH_KEY);
        }
        if (window.location.pathname !== "/" || window.location.search || window.location.hash) {
          window.history.replaceState(window.history.state, "", "/");
        }
      }
      await signInWithRedirect({ provider: "Google" });
    } catch (error) {
      setBusy(false);
      setError(formatAuthFailure(error));
    }
  };

  const signOutCurrentUser = async () => {
    configureAmplifyClient();
    setBusy(true);
    setError(null);
    try {
      await signOut();
      await refreshAuthState();
    } catch {
      setError("Sign-out failed");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!externalAuthState) return;
    setAuthState(externalAuthState);
  }, [externalAuthState]);

  const signedIn = authState.status === "signedIn";
  const actionLabel = signedIn ? "LOGOUT" : "LOGIN";
  const Container = renderAction ? "div" : "span";
  return (
    <Container className={className ? `reader-auth ${className}` : "reader-auth"} aria-live="polite" data-footer-utility={dataFooterUtility}>
      {signedIn && showIdentity ? <span className="reader-auth__identity">{authState.label}</span> : null}
      {error ? <span className="reader-auth__error">{error}</span> : null}
      {renderAction ? renderAction({ disabled: authState.status === "loading" || busy, onClick: signedIn ? signOutCurrentUser : signIn, signedIn }) : <button
        className="reader-auth__button"
        disabled={authState.status === "loading" || busy}
        onClick={signedIn ? signOutCurrentUser : signIn}
        type="button"
      >
        {actionLabel}
      </button>}
    </Container>
  );
}

function formatAuthFailure(error: unknown): string {
  const detail = extractAuthFailureDetail(error);
  return detail ? `Sign-in failed: ${detail}` : "Sign-in failed";
}

function extractAuthFailureDetail(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === "string") return error;
  if (typeof error !== "object") return null;

  const record = error as Record<string, unknown>;
  const message = record.message;
  if (typeof message === "string" && message.trim().length > 0) return message;
  const name = record.name;
  if (typeof name === "string" && name.trim().length > 0) return name;

  const nested = record.error;
  if (nested && nested !== error) return extractAuthFailureDetail(nested);
  return null;
}
