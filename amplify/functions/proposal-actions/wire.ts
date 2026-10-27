import type { ITable } from "aws-cdk-lib/aws-dynamodb";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

/**
 * Least-privilege wiring for proposal-actions: read and write on the Proposal table and nothing else, with the table's
 * name in `PAPYRUS_PROPOSAL_TABLE`. Every site gets this, with or without the reader-steering plugin.
 */
export function wireProposalActions(backend: any): void {
  const lambda = backend.proposalActions.resources.lambda as LambdaFunction;
  const table = (backend.data.resources.tables as Record<string, ITable>).Proposal;
  table.grantReadWriteData(lambda);
  lambda.addEnvironment("PAPYRUS_PROPOSAL_TABLE", table.tableName);
}
