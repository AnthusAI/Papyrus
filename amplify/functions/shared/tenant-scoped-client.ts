/**
 * The Amplify data client of one call, scoped to the tenant its context names (TypeScript twin of PapyrusGraphQLAuthoringClient(tenant_id=...)).
 * On a SHARED stack every model that carries a `tenantId` answers only with the caller's tenant's rows: a `get` of another tenant's id returns
 * nothing (so the handler says "not found"), an index query or list drops foreign rows, a create is stamped with the caller's tenant (a payload that
 * names another is refused), and an update or delete first reads the row and refuses one that is not the caller's. On a DEDICATED stack the client
 * is returned as it is: its single tenant is the whole backend.
 */
import { TENANT_FIELD_MODELS, TENANT_MODELS, tenantScopedValue } from "../../../lib/tenant-keys";
import type { TenantContext } from "./tenant-context";

type Row = Record<string, any>;
type Result = { data?: Row | Row[] | null; errors?: unknown; nextToken?: string | null };
type Model = Record<string, (...args: any[]) => Promise<Result>>;
type ScopableClient = { models: Record<string, any> };

const MUTATORS = new Set(["create", "update", "delete"]);

function belongs(tenantId: string, row: Row | null | undefined): boolean {
  return !row || row.tenantId === tenantId;
}

function scopedModel(name: string, model: Model, tenantId: string): Model {
  return new Proxy(model, {
    get(target, member: string) {
      const operation = target[member];
      if (typeof operation !== "function") return operation;
      if (member === "get") {
        return async (...args: any[]): Promise<Result> => {
          const result = await operation.apply(target, args);
          return !result.data || Array.isArray(result.data) || belongs(tenantId, result.data) ? result : { ...result, data: null };
        };
      }
      if (member === "create") {
        return async (input: Row, ...rest: any[]): Promise<Result> => {
          if (input.tenantId !== undefined && input.tenantId !== null && input.tenantId !== tenantId) {
            throw new Error(`${name} cannot be created for another tenant.`);
          }
          return operation.call(target, { ...input, tenantId }, ...rest);
        };
      }
      if (MUTATORS.has(member)) {
        return async (input: Row, ...rest: any[]): Promise<Result> => {
          const current = await target.get({ id: input.id });
          if (!current.data || Array.isArray(current.data) || !belongs(tenantId, current.data)) throw new Error(`${name} ${input.id} was not found.`);
          if (input.tenantId !== undefined && input.tenantId !== null && input.tenantId !== tenantId) throw new Error(`${name} cannot move to another tenant.`);
          return operation.call(target, input, ...rest);
        };
      }
      return async (...args: any[]): Promise<Result> => {
        const result = await operation.apply(target, args);
        return Array.isArray(result.data) ? { ...result, data: result.data.filter((row) => belongs(tenantId, row)) } : result;
      };
    },
  });
}

export function tenantScopedClient<Client extends ScopableClient>(client: Client, context: TenantContext): Client {
  if (context.mode !== "shared") return client;
  const tenantId = context.tenantId;
  if (!tenantId) throw new Error("A shared stack's call has a tenant before it has a client.");
  const models = new Proxy(client.models, {
    get(target, name: string) {
      const model = target[name];
      return TENANT_MODELS.has(name) || TENANT_FIELD_MODELS.has(name) ? scopedModel(name, model, tenantId) : model;
    },
  });
  return { ...client, models } as Client;
}

/** A record id that is the same for every tenant today (a singleton such as the Newsroom summary), as this stack stores it. */
export function scopedRecordId(context: TenantContext, id: string): string {
  return context.mode === "shared" && context.tenantId ? tenantScopedValue(context.tenantId, id) : id;
}

const NEWSROOM_SUMMARY_BASE_ID = "knowledge-raw-payload-newsroom-summary-current";

/** The id of the call's tenant's Newsroom summary snapshot: the one record id every tenant would otherwise share. */
export function newsroomSummaryPayloadId(context: TenantContext): string {
  return scopedRecordId(context, NEWSROOM_SUMMARY_BASE_ID);
}
