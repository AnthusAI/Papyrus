/**
 * One-off, idempotent: puts a PublicHandleClaim for every UserProfile that already has a public handle, so handles set before the
 * claim records existed are held like new ones. Each put is conditional (the claim is absent or already that profile's), so a rerun
 * changes nothing and two profiles sharing a handle are reported as conflicts instead of overwritten. An operator with IAM runs it per site:
 *
 *   tsx scripts/backfill-public-handle-claims.ts --profile-table <UserProfile table> --claim-table <PublicHandleClaim table> [--dry-run]
 */
import { ConditionalCheckFailedException, DynamoDBClient, PutItemCommand, ScanCommand } from "@aws-sdk/client-dynamodb";

function option(name: string): string | undefined {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const profileTable = option("profile-table");
const claimTable = option("claim-table");
const dryRun = process.argv.includes("--dry-run");
if (!profileTable || !claimTable) {
  console.error("Usage: tsx scripts/backfill-public-handle-claims.ts --profile-table <name> --claim-table <name> [--dry-run]");
  process.exit(2);
}

const client = new DynamoDBClient({});
const report = { profilesWithHandles: 0, claimed: 0, conflicts: [] as Array<{ handle: string; profileId: string }> };

let startKey: Record<string, any> | undefined;
do {
  const page = await client.send(new ScanCommand({ TableName: profileTable, ProjectionExpression: "id, publicHandle", ExclusiveStartKey: startKey }));
  for (const item of page.Items ?? []) {
    const handle = item.publicHandle?.S?.trim().toLowerCase();
    const profileId = item.id?.S;
    if (!handle || !profileId) continue;
    report.profilesWithHandles += 1;
    if (dryRun) continue;
    try {
      await client.send(new PutItemCommand({
        TableName: claimTable,
        Item: {
          id: { S: handle },
          __typename: { S: "PublicHandleClaim" },
          ownerKind: { S: "staff" },
          ownerId: { S: profileId },
          claimedAt: { S: new Date().toISOString() },
        },
        ConditionExpression: "attribute_not_exists(id) OR ownerId = :me",
        ExpressionAttributeValues: { ":me": { S: profileId } },
      }));
      report.claimed += 1;
    } catch (error) {
      if (!(error instanceof ConditionalCheckFailedException)) throw error;
      report.conflicts.push({ handle, profileId });
    }
  }
  startKey = page.LastEvaluatedKey;
} while (startKey);

console.log(JSON.stringify(report, null, 2));
