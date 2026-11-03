import type { NextConfig } from "next";
export function withPapyrus(nextConfig?: NextConfig, options?: { root?: string; projectionPath?: string }): NextConfig;
export const READER_EXPIRE_TIME_SECONDS: number;
export const DEFAULT_STATIC_GENERATION_WORKERS: number;
export const DEFAULT_STATIC_GENERATION_CONCURRENCY: number;
export const DEFAULT_STATIC_GENERATION_RETRY_COUNT: number;
export function staticGenerationSettings(): {
  cpus: number;
  staticGenerationMaxConcurrency: number;
  staticGenerationRetryCount: number;
};
export function redirectChatticusZod(resource: { request: string; context?: string }): void;
export function projectionTypesSlice(projection: Record<string, unknown>): Record<string, unknown>;
export function projectionTypesEnvironment(root: string, projectionPath?: string): Record<string, string>;
