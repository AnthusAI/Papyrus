"use client";

import { Hub } from "aws-amplify/utils";
import { isUnauthenticatedError } from "./reader-auth-state";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { DevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";
import type { CategorySteeringDashboard } from "../lib/category-repository";
import { ensureDevSandboxEditorSession } from "./dev-sandbox-editor-sign-in";
import { discardReferencesHeadStart, prefetchReferencesFeed, wantsReferencesHeadStart } from "./references-prefetch";
import { SITE_BRAND } from "../lib/site-brand";
import { clearSavedNewsroomDisplay, loadSessionDisplay, saveSessionDisplay } from "../lib/reference-feed-cache";
import {
  loadEditorAssignmentsData,
  loadEditorDoctrineRecordsData,
  loadEditorNewsDeskDashboard,
  loadEditorResolvedAccessState,
  loadEditorUserDirectoryData,
} from "./news-desk-taxonomy-client";
import {
  beginAccessCheck,
  beginDeskLoad,
  createInitialNewsDeskShellState,
  patchDashboard,
  resolveAccessFailure,
  resolveDashboardFailure,
  resolveDashboardReady,
  resolveForbidden,
  resolveSignedOut,
  type NewsDeskShellState,
} from "../lib/news-desk-session";

export type NewsDeskSearchTransition = {
  href: string;
  kind: "modal-to-serp";
  requestKey: string;
  submittedAt: number;
};

type NewsDeskClientContextValue = {
  beginSearchTransition: (transition: NewsDeskSearchTransition) => void;
  clearSearchTransition: () => void;
  shell: NewsDeskShellState;
  searchTransition: NewsDeskSearchTransition | null;
  refreshDashboard: () => Promise<void>;
  refreshAssignments: () => Promise<void>;
  refreshDoctrineRecords: () => Promise<void>;
  refreshUserDirectory: () => Promise<void>;
};

const NewsDeskClientContext = createContext<NewsDeskClientContextValue | null>(null);

export function NewsDeskClientProvider({
  children,
  devSandboxEditorAuth = null,
  localPreviewDashboard = null,
}: Readonly<{
  children: React.ReactNode;
  devSandboxEditorAuth?: DevSandboxEditorAuth | null;
  localPreviewDashboard?: CategorySteeringDashboard | null;
}>) {
  const [shell, setShell] = useState<NewsDeskShellState>(() => createInitialNewsDeskShellState());
  const [searchTransition, setSearchTransition] = useState<NewsDeskSearchTransition | null>(null);
  const shellRef = useRef(shell);
  const bootstrapSequenceRef = useRef(0);

  useEffect(() => {
    shellRef.current = shell;
  }, [shell]);

  const refreshDashboard = useCallback(async () => {
    const sequence = ++bootstrapSequenceRef.current;
    if (localPreviewDashboard) {
      setShell((current) => resolveDashboardReady(
        current,
        localPreviewDashboard,
        { status: "signedIn", label: "Local preview editor", email: null },
        new Date().toISOString(),
      ));
      return;
    }
    // A recent confirmed session is shown (name, "loading" instead of "checking") while the real check runs again.
    // Display only: the check below still decides access, and the backend authorizes every call.
    const remembered = loadSessionDisplay(SITE_BRAND.id);
    setShell((current) => (remembered && !current.dashboard
      ? { ...beginAccessCheck(current), phase: "loadingDesk" as const, auth: { status: "signedIn" as const, label: remembered.label } }
      : beginAccessCheck(current)));

    try {
      await ensureDevSandboxEditorSession(devSandboxEditorAuth);
    } catch (error) {
      console.error("[PapyrusDevAuth] Sandbox editor auto sign-in failed:", error);
    }
    if (bootstrapSequenceRef.current !== sequence) return;

    const access = await loadEditorResolvedAccessState();
    if (bootstrapSequenceRef.current !== sequence) return;

    if (access.status === "signedOut") {
      clearSavedNewsroomDisplay(SITE_BRAND.id);
      discardReferencesHeadStart();
      setShell((current) => resolveSignedOut(current, access.auth));
      return;
    }
    if (access.status === "forbidden") {
      setShell((current) => resolveForbidden(current, access.auth));
      return;
    }
    if (access.status === "error") {
      setShell((current) => resolveAccessFailure(current, access.error));
      return;
    }

    saveSessionDisplay(SITE_BRAND.id, { label: access.auth.label, isAdmin: access.isAdmin });
    setShell((current) => beginDeskLoad(current, access.auth));
    // The References reads do not depend on the summary dashboard: start them now, side by side with it.
    if (typeof window !== "undefined" && wantsReferencesHeadStart(window.location.pathname)) prefetchReferencesFeed();

    try {
      const dashboard = await loadEditorNewsDeskDashboard({ isAdmin: access.isAdmin });
      if (bootstrapSequenceRef.current !== sequence) return;
      setShell((current) => resolveDashboardReady(current, dashboard, access.auth, new Date().toISOString()));
    } catch (error) {
      if (bootstrapSequenceRef.current !== sequence) return;
      if (isUnauthenticatedError(error)) {
        setShell((current) => resolveSignedOut(current, { status: "signedOut", label: "Signed out" }));
        return;
      }
      if (isAuthorizationError(error)) {
        // The session already has editor rights, so the backend refusing a read is not a missing role. Say what was refused.
        setShell((current) => resolveDashboardFailure(current, access.auth, refusedReadMessage(error)));
        return;
      }
      setShell((current) => resolveDashboardFailure(
        current,
        access.auth,
        error instanceof Error ? error.message : "Could not load Newsroom data.",
      ));
    }
  }, [devSandboxEditorAuth, localPreviewDashboard]);

  const refreshAssignments = useCallback(async () => {
    try {
      const assignmentState = await loadEditorAssignmentsData();
      setShell((current) => patchDashboard(
        current,
        (dashboard) => ({
          ...dashboard,
          assignments: assignmentState.assignments,
          assignmentEvents: assignmentState.assignmentEvents,
        }),
        new Date().toISOString(),
      ));
    } catch (error) {
      const auth = shellRef.current.auth;
      setShell((current) => resolvePrivateReadFailure(current, auth, error, "Could not refresh assignments."));
    }
  }, []);

  const refreshDoctrineRecords = useCallback(async () => {
    try {
      const doctrineRecords = await loadEditorDoctrineRecordsData({ dashboard: shellRef.current.dashboard });
      setShell((current) => patchDashboard(
        current,
        (dashboard) => ({
          ...dashboard,
          doctrineRecords,
        }),
        new Date().toISOString(),
      ));
    } catch (error) {
      const auth = shellRef.current.auth;
      setShell((current) => resolvePrivateReadFailure(current, auth, error, "Could not refresh doctrine records."));
    }
  }, []);

  const refreshUserDirectory = useCallback(async () => {
    if (!shellRef.current.dashboard?.canManageUsers) return;
    try {
      const userDirectory = await loadEditorUserDirectoryData();
      setShell((current) => patchDashboard(
        current,
        (dashboard) => ({
          ...dashboard,
          userDirectory,
        }),
        new Date().toISOString(),
      ));
    } catch (error) {
      const auth = shellRef.current.auth;
      setShell((current) => resolvePrivateReadFailure(current, auth, error, "Could not refresh the user directory."));
    }
  }, []);

  useEffect(() => {
    void refreshDashboard();
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedOut") {
        bootstrapSequenceRef.current += 1;
        clearSavedNewsroomDisplay(SITE_BRAND.id);
        discardReferencesHeadStart();
        setShell((current) => resolveSignedOut(current, { status: "signedOut", label: "Signed out" }));
        return;
      }
      if (
        payload.event === "signedIn" ||
        payload.event === "signInWithRedirect" ||
        payload.event === "signInWithRedirect_failure"
      ) {
        void refreshDashboard();
      }
    });
    return () => unsubscribe();
  }, [refreshDashboard]);

  const value = useMemo<NewsDeskClientContextValue>(() => ({
    beginSearchTransition: (transition) => setSearchTransition(transition),
    clearSearchTransition: () => setSearchTransition(null),
    shell,
    searchTransition,
    refreshDashboard,
    refreshAssignments,
    refreshDoctrineRecords,
    refreshUserDirectory,
  }), [refreshAssignments, refreshDashboard, refreshDoctrineRecords, refreshUserDirectory, searchTransition, shell]);

  return <NewsDeskClientContext.Provider value={value}>{children}</NewsDeskClientContext.Provider>;
}

function isAuthorizationError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /not authorized|unauthorized|access denied|forbidden/i.test(message);
}

function refusedReadMessage(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  return `The Newsroom backend refused a read for this signed-in account (${detail}). The account has editor or admin rights, so this is a backend authorization rule, not a missing role.`;
}

function resolvePrivateReadFailure(state: NewsDeskShellState, auth: NewsDeskShellState["auth"], error: unknown, fallback: string): NewsDeskShellState {
  if (isUnauthenticatedError(error)) return resolveSignedOut(state, { status: "signedOut", label: "Signed out" });
  if (isAuthorizationError(error)) return resolveDashboardFailure(state, auth, refusedReadMessage(error));
  return resolveDashboardFailure(state, auth, error instanceof Error ? error.message : fallback);
}

export function useOptionalNewsDeskClient() {
  return useContext(NewsDeskClientContext);
}
