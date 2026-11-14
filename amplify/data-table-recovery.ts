import type { AmplifyDynamoDbTableWrapper } from "@aws-amplify/graphql-api-construct";

export function enablePointInTimeRecoveryOnDataTables(amplifyDynamoDbTables: Record<string, AmplifyDynamoDbTableWrapper>): string[] {
  const tableNames = Object.keys(amplifyDynamoDbTables);
  for (const tableName of tableNames) {
    amplifyDynamoDbTables[tableName].pointInTimeRecoveryEnabled = true;
  }
  return tableNames;
}
