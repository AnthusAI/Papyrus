import type { AccountLinkingOutputs } from "../skill-package";
import type { LwaCredentials, SmapiClient } from "./smapi";

/** SSM Parameter Store, both kinds. `get` decrypts. */
export interface ParameterStore {
  get(name: string): Promise<string | undefined>;
  /** A plain String parameter (overwrites). */
  putString(name: string, value: string): Promise<void>;
}

/** The skill function's resource policy, as far as the sync touches it. */
export interface FunctionPermissions {
  /** The Alexa-service statements: their ids and the skill ID each is scoped to (`undefined` = any skill). */
  alexaStatements(functionArn: string): Promise<{ statementId: string; skillId: string | undefined }[]>;
  addSkillPermission(functionArn: string, statementId: string, skillId: string): Promise<void>;
  removePermission(functionArn: string, statementId: string): Promise<void>;
}

/** The account linking client's secret, read at sync time from Cognito so no copy is stored anywhere. */
export interface ClientSecretSource {
  clientSecret(outputs: AccountLinkingOutputs): Promise<string | undefined>;
}

export type SyncPorts = {
  parameters: ParameterStore;
  permissions: FunctionPermissions;
  clientSecrets: ClientSecretSource;
  /** Connects to Amazon with the shared developer account's credentials. */
  connect: (credentials: LwaCredentials) => Promise<SmapiClient>;
  log: (line: string) => void;
};
