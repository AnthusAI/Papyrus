/**
 * The newsletter plugin adds nothing to the GraphQL schema: subscriber records are personal data kept in the plugin's own
 * DynamoDB table, never readable through the content API. Later stories add custom newsroom operations here.
 */
export function newsletterSchemaDefinitions(): Record<string, unknown> {
  return {};
}
