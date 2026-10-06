import { AsyncLocalStorage } from "node:async_hooks";
import { getContentSource, type ContentSource } from "./site-env";

export type ContentSourceContext = {
  source: ContentSource;
};

const contentSourceStorage = new AsyncLocalStorage<ContentSourceContext>();

export function runWithContentSource<T>(source: ContentSource, operation: () => Promise<T>): Promise<T> {
  return contentSourceStorage.run({ source }, operation);
}

export function currentContentSource(): ContentSource {
  return contentSourceStorage.getStore()?.source ?? getContentSource();
}
