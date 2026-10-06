import { generateClient } from "aws-amplify/data";
import { getUrl, uploadData } from "aws-amplify/storage";
import type { Schema } from "../amplify/data/resource";
import type { MediaAssetFields, MediaAssetRecord, NewsroomMediaBackend } from "./newsroom-media";

type MediaListPage = {
  data?: (Record<string, unknown> | null)[] | null;
  nextToken?: string | null;
  errors?: { message?: string }[] | null;
};

export type MediaDataClient = {
  models: {
    MediaAsset: {
      create: (
        input: MediaAssetFields,
        options: { authMode: "userPool" },
      ) => Promise<{ errors?: { message?: string }[] | null }>;
      listMediaAssetsByItemAndSortKey: (
        input: { itemId: string },
        options: { authMode: "userPool"; nextToken?: string | null; limit?: number },
      ) => Promise<MediaListPage>;
    };
  };
};

export type MediaStorageApi = {
  upload: (input: { path: string; data: Blob; contentType: string }) => Promise<void>;
  signedUrl: (path: string) => Promise<string>;
};

function failOnErrors(errors: { message?: string }[] | null | undefined): void {
  if (errors && errors.length > 0) {
    throw new Error(errors.map((error) => error.message ?? "GraphQL error").join("; "));
  }
}

function srcPathFromMetadata(metadata: unknown): string | null {
  let parsed = metadata;
  if (typeof metadata === "string") {
    try {
      parsed = JSON.parse(metadata);
    } catch {
      return null;
    }
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const srcPath = (parsed as Record<string, unknown>).srcPath;
  return typeof srcPath === "string" ? srcPath : null;
}

export function createMediaBackend(client: () => MediaDataClient, storage: MediaStorageApi): NewsroomMediaBackend {
  return {
    uploadImage: ({ storagePath, data, contentType }) =>
      storage.upload({ path: storagePath, data, contentType }),
    async createMediaAsset(fields) {
      const response = await client().models.MediaAsset.create(fields, { authMode: "userPool" });
      failOnErrors(response.errors);
    },
    async listMediaAssets(itemId) {
      const records: MediaAssetRecord[] = [];
      let nextToken: string | null | undefined = null;
      do {
        const page: MediaListPage = await client().models.MediaAsset.listMediaAssetsByItemAndSortKey(
          { itemId },
          { authMode: "userPool", nextToken, limit: 500 },
        );
        failOnErrors(page.errors);
        for (const row of page.data ?? []) {
          if (!row) continue;
          records.push({
            id: String(row.id),
            sortKey: String(row.sortKey),
            storagePath: typeof row.storagePath === "string" ? row.storagePath : null,
            alt: typeof row.alt === "string" ? row.alt : "",
            srcPath: srcPathFromMetadata(row.metadata),
          });
        }
        nextToken = page.nextToken;
      } while (nextToken);
      return records;
    },
    imageUrl: (storagePath) => storage.signedUrl(storagePath),
  };
}

const amplifyStorage: MediaStorageApi = {
  async upload({ path, data, contentType }) {
    await uploadData({ path, data, options: { contentType } }).result;
  },
  async signedUrl(path) {
    const { url } = await getUrl({ path });
    return url.toString();
  },
};

export function createLiveMediaBackend(): NewsroomMediaBackend {
  let client: MediaDataClient | null = null;
  return createMediaBackend(() => {
    if (!client) client = generateClient<Schema>() as unknown as MediaDataClient;
    return client;
  }, amplifyStorage);
}

export function createDemoMediaBackend(): NewsroomMediaBackend {
  const objects = new Map<string, Blob>();
  const rows = new Map<string, MediaAssetFields[]>();
  return {
    async uploadImage({ storagePath, data }) {
      objects.set(storagePath, data);
    },
    async createMediaAsset(fields) {
      rows.set(fields.itemId, [...(rows.get(fields.itemId) ?? []), fields]);
    },
    async listMediaAssets(itemId) {
      return (rows.get(itemId) ?? []).map((fields) => ({
        id: fields.id,
        sortKey: fields.sortKey,
        storagePath: fields.storagePath,
        alt: fields.alt,
        srcPath: srcPathFromMetadata(fields.metadata),
      }));
    },
    async imageUrl(storagePath) {
      const object = objects.get(storagePath);
      if (!object) throw new Error(`No demo object at ${storagePath}.`);
      return URL.createObjectURL(object);
    },
  };
}

let liveBackend: NewsroomMediaBackend | null = null;
let demoBackend: NewsroomMediaBackend | null = null;

export function resolveMediaBackend(demo: boolean): NewsroomMediaBackend {
  if (demo) {
    demoBackend ??= createDemoMediaBackend();
    return demoBackend;
  }
  liveBackend ??= createLiveMediaBackend();
  return liveBackend;
}
