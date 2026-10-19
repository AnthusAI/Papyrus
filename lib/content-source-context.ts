import { AsyncLocalStorage } from "node:async_hooks";
import { getContentSource, type ContentSource } from "./site-env";
import { tenantIdFromEnvironment } from "./tenant-keys";

export type ContentSourceContext = {
  source: ContentSource;
  /** Request-scoped data client (drafts mode: carries the visitor's session cookies). */
  client?: unknown;
  /** Tenant of the selected Prospectus account; falls back to PAPYRUS_TENANT_ID. */
  tenantId?: string;
};

const contentSourceStorage = new AsyncLocalStorage<ContentSourceContext>();

export function runWithContentSource<T>(
  source: ContentSource,
  operation: () => Promise<T>,
  client?: unknown,
  tenantId?: string,
): Promise<T> {
  return contentSourceStorage.run({ source, client, tenantId }, operation);
}

export function currentTenantId(): string | undefined {
  return contentSourceStorage.getStore()?.tenantId ?? tenantIdFromEnvironment();
}

export function currentRequestClient<T>(): T | undefined {
  return contentSourceStorage.getStore()?.client as T | undefined;
}

export function currentContentSource(): ContentSource {
  return contentSourceStorage.getStore()?.source ?? getContentSource();
}
