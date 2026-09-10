"use client";

import { Hub } from "aws-amplify/utils";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { DevSandboxEditorAuth } from "../lib/dev-sandbox-editor-auth";
import { ensureDevSandboxEditorSession } from "./dev-sandbox-editor-sign-in";
import {
  loadEditorAssignmentsData,
  loadEditorDoctrineRecordsData,
  loadEditorNewsDeskDashboard,
  loadEditorResolvedAccessState,
  loadEditorUserDirectoryData,
} from "./news-desk-taxonomy-client";
import {
  beginAccessCheck,
  beginAuthenticatedDeskHydration,
  createInitialNewsDeskShellState,
  patchDashboard,
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
}: Readonly<{ children: React.ReactNode; devSandboxEditorAuth?: DevSandboxEditorAuth | null }>) {
  const [shell, setShell] = useState<NewsDeskShellState>(() => createInitialNewsDeskShellState());
  const [searchTransition, setSearchTransition] = useState<NewsDeskSearchTransition | null>(null);
  const shellRef = useRef(shell);
  const bootstrapSequenceRef = useRef(0);

  useEffect(() => {
    shellRef.current = shell;
  }, [shell]);

  const refreshDashboard = useCallback(async () => {
    const sequence = ++bootstrapSequenceRef.current;
    setShell((current) => beginAccessCheck(current));

    try {
      await ensureDevSandboxEditorSession(devSandboxEditorAuth);
    } catch (error) {
      console.error("[PapyrusDevAuth] Sandbox editor auto sign-in failed:", error);
    }
    if (bootstrapSequenceRef.current !== sequence) return;

    const access = await loadEditorResolvedAccessState();
    if (bootstrapSequenceRef.current !== sequence) return;

    if (access.status === "signedOut") {
      setShell((current) => resolveSignedOut(current, access.auth));
      return;
    }
    if (access.status === "forbidden") {
      setShell((current) => resolveForbidden(current, access.auth));
      return;
    }
    if (access.status === "error") {
      setShell((current) => resolveDashboardFailure(current, access.auth, access.error));
      return;
    }

    setShell((current) => beginAuthenticatedDeskHydration(current, access.auth, { canManageUsers: access.isAdmin }));

    try {
      const dashboard = await loadEditorNewsDeskDashboard({ isAdmin: access.isAdmin });
      if (bootstrapSequenceRef.current !== sequence) return;
      setShell((current) => resolveDashboardReady(current, dashboard, access.auth, new Date().toISOString()));
    } catch (error) {
      if (bootstrapSequenceRef.current !== sequence) return;
      if (isAuthorizationError(error)) {
        setShell((current) => resolveForbidden(current, access.auth));
        return;
      }
      setShell((current) => resolveDashboardFailure(
        current,
        access.auth,
        error instanceof Error ? error.message : "Could not load Newsroom data.",
      ));
    }
  }, [devSandboxEditorAuth]);

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
      setShell((current) => resolveDashboardFailure(
        current,
        auth,
        error instanceof Error ? error.message : "Could not refresh assignments.",
      ));
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
      setShell((current) => resolveDashboardFailure(
        current,
        auth,
        error instanceof Error ? error.message : "Could not refresh doctrine records.",
      ));
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
      setShell((current) => resolveDashboardFailure(
        current,
        auth,
        error instanceof Error ? error.message : "Could not refresh the user directory.",
      ));
    }
  }, []);

  useEffect(() => {
    void refreshDashboard();
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedOut") {
        bootstrapSequenceRef.current += 1;
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

export function useOptionalNewsDeskClient() {
  return useContext(NewsDeskClientContext);
}
