import { AsyncLocalStorage } from "node:async_hooks";
import { getContentSource, type ContentSource } from "./site-env";

export type ContentSourceContext = {
  source: ContentSource;
  /** Request-scoped data client (drafts mode: carries the visitor's session cookies). */
  client?: unknown;
};

const contentSourceStorage = new AsyncLocalStorage<ContentSourceContext>();

export function runWithContentSource<T>(
  source: ContentSource,
  operation: () => Promise<T>,
  client?: unknown,
): Promise<T> {
  return contentSourceStorage.run({ source, client }, operation);
}

export function currentRequestClient<T>(): T | undefined {
  return contentSourceStorage.getStore()?.client as T | undefined;
}

export function currentContentSource(): ContentSource {
  return contentSourceStorage.getStore()?.source ?? getContentSource();
}
