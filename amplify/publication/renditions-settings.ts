/**
 * Pure planning for the upload-time renditions function of an s3-projection
 * site (no CDK imports, so it can be tested without synthesizing).
 *
 * The function exists only for a site whose `projection.json` carries an
 * `images` section (the one place the image pipeline settings live, shared by
 * the renditions function and the projector) or `media.originals: true`
 * (every media object is also published as is, at its key without `media/`).
 */
import fs from "node:fs";
import path from "node:path";

export const RENDITIONS_MEMORY_MB = 3008;
export const RENDITIONS_TIMEOUT_SECONDS = 300;
export const RENDITIONS_EPHEMERAL_STORAGE_MB = 2048;
export const RENDITIONS_STATIC_DIRECTORY = "/var/task/site_static";
export const RENDITIONS_MEDIA_PREFIX = "media/";
export const RENDITIONS_FUNCTION_NAME_ENV = "PAPYRUS_RENDITIONS_FUNCTION_NAME";

export type RenditionsPlan = {
  enabled: boolean;
  siteFiles: Array<{ from: string; to: string }>;
};

export function projectionSettingsHaveImages(settingsPath: string): boolean {
  if (!fs.existsSync(settingsPath)) return false;
  const parsed = JSON.parse(fs.readFileSync(settingsPath, "utf8")) as Record<string, unknown>;
  return typeof parsed.images === "object" && parsed.images !== null;
}

export function projectionSettingsPublishOriginals(settingsPath: string): boolean {
  if (!fs.existsSync(settingsPath)) return false;
  const parsed = JSON.parse(fs.readFileSync(settingsPath, "utf8")) as { media?: { originals?: unknown } };
  return parsed.media?.originals === true;
}

export function planRenditions(publication: { staticDir?: string } | undefined, workingDirectory: string): RenditionsPlan {
  if (publication?.staticDir === undefined) return { enabled: false, siteFiles: [] };
  const settingsFile = path.join(publication.staticDir, "projection.json");
  const resolved = path.resolve(workingDirectory, settingsFile);
  if (!projectionSettingsHaveImages(resolved) && !projectionSettingsPublishOriginals(resolved)) return { enabled: false, siteFiles: [] };
  return { enabled: true, siteFiles: [{ from: settingsFile, to: "site_static/projection.json" }] };
}

export function renditionsEventPattern(mediaBucketName: string): Record<string, unknown> {
  return {
    source: ["aws.s3"],
    detailType: ["Object Created"],
    detail: { bucket: { name: [mediaBucketName] }, object: { key: [{ prefix: RENDITIONS_MEDIA_PREFIX }] } },
  };
}

export function renditionsEnvironment(siteBucketName: string): Record<string, string> {
  return {
    PAPYRUS_SITE_BUCKET: siteBucketName,
    PAPYRUS_SITE_STATIC_DIR: RENDITIONS_STATIC_DIRECTORY,
  };
}
