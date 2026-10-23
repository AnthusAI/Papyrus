import type { CategorySteeringDashboard } from "./category-repository";
import type { ReaderAuthSnapshot } from "../components/reader-auth-state";

export type NewsDeskShellPhase =
  | "checkingAccess"
  | "loadingDesk"
  | "ready"
  | "refreshing"
  | "signedOut"
  | "forbidden"
  | "error";

export type NewsDeskShellState = {
  phase: NewsDeskShellPhase;
  auth: ReaderAuthSnapshot;
  dashboard: CategorySteeringDashboard | null;
  lastRefreshedAt: string | null;
  stale: boolean;
  error: string | null;
};

export function createInitialNewsDeskShellState(): NewsDeskShellState {
  return {
    phase: "checkingAccess",
    auth: { status: "loading", label: "Checking sign-in" },
    dashboard: null,
    lastRefreshedAt: null,
    stale: false,
    error: null,
  };
}

export function beginAccessCheck(state: NewsDeskShellState): NewsDeskShellState {
  if (state.dashboard) {
    return {
      ...state,
      phase: "refreshing",
      stale: false,
      error: null,
    };
  }

  return {
    ...state,
    phase: "checkingAccess",
    stale: false,
    error: null,
  };
}

export function beginDeskLoad(state: NewsDeskShellState, auth: ReaderAuthSnapshot): NewsDeskShellState {
  return {
    ...state,
    phase: state.dashboard ? "refreshing" : "loadingDesk",
    auth,
    stale: false,
    error: null,
  };
}

export function resolveSignedOut(state: NewsDeskShellState, auth: ReaderAuthSnapshot): NewsDeskShellState {
  return {
    ...state,
    phase: "signedOut",
    auth,
    dashboard: null,
    stale: false,
    error: null,
  };
}

export function resolveForbidden(state: NewsDeskShellState, auth: ReaderAuthSnapshot): NewsDeskShellState {
  return {
    ...state,
    phase: "forbidden",
    auth,
    dashboard: null,
    stale: false,
    error: null,
  };
}

export function resolveDashboardReady(
  state: NewsDeskShellState,
  dashboard: CategorySteeringDashboard,
  auth: ReaderAuthSnapshot,
  refreshedAt: string,
): NewsDeskShellState {
  return {
    ...state,
    phase: "ready",
    auth,
    dashboard,
    lastRefreshedAt: refreshedAt,
    stale: false,
    error: null,
  };
}

export function resolveDashboardFailure(
  state: NewsDeskShellState,
  auth: ReaderAuthSnapshot,
  error: string,
): NewsDeskShellState {
  if (state.dashboard) {
    return {
      ...state,
      phase: "ready",
      auth,
      stale: true,
      error,
    };
  }

  return {
    ...state,
    phase: "error",
    auth,
    dashboard: null,
    stale: false,
    error,
  };
}

/** An unverified session must never leave private records on screen. */
export function resolveAccessFailure(state: NewsDeskShellState, error: string): NewsDeskShellState {
  return {
    ...state,
    phase: "error",
    auth: { status: "signedOut", label: "Signed out" },
    dashboard: null,
    stale: false,
    error,
  };
}

export function patchDashboard(
  state: NewsDeskShellState,
  patch: (dashboard: CategorySteeringDashboard) => CategorySteeringDashboard,
  refreshedAt: string,
): NewsDeskShellState {
  if (!state.dashboard) return state;
  return {
    ...state,
    phase: "ready",
    dashboard: patch(state.dashboard),
    lastRefreshedAt: refreshedAt,
    stale: false,
    error: null,
  };
}
