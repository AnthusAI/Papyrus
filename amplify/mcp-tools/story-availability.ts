import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import type { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

type StoryTables = { Item?: ITable; ReviewRequest?: ITable; EditorialCheckSettings?: ITable };

/** The publish gate needs both review requests and its editorial setting model. */
export function storyPublicationRequestsAvailable(tables: StoryTables): boolean {
  return Boolean(tables.Item && tables.ReviewRequest && tables.EditorialCheckSettings);
}

/** An excluded model group has no table; don't dereference it or grant access to it. */
export function wireMcpStoryTables(fn: Pick<LambdaFunction, 'addEnvironment' | 'addToRolePolicy'>, tables: StoryTables): void {
  const item = tables.Item;
  if (item) {
    fn.addEnvironment('PAPYRUS_ITEM_TABLE', item.tableName);
    fn.addToRolePolicy(new PolicyStatement({ actions: ['dynamodb:PutItem', 'dynamodb:UpdateItem'], resources: [item.tableArn], conditions: { 'ForAnyValue:StringEquals': { 'dynamodb:EnclosingOperation': ['TransactWriteItems'] } } }));
  }
  const review = tables.ReviewRequest;
  if (item && review && storyPublicationRequestsAvailable(tables)) {
    fn.addEnvironment('PAPYRUS_REVIEW_REQUEST_TABLE', review.tableName);
    fn.addEnvironment('PAPYRUS_MCP_STORY_PUBLISH_REQUEST_ENABLED', 'true');
    fn.addToRolePolicy(new PolicyStatement({ actions: ['dynamodb:ConditionCheckItem'], resources: [item.tableArn], conditions: { 'ForAnyValue:StringEquals': { 'dynamodb:EnclosingOperation': ['TransactWriteItems'] } } }));
    fn.addToRolePolicy(new PolicyStatement({ actions: ['dynamodb:PutItem'], resources: [review.tableArn], conditions: { 'ForAnyValue:StringEquals': { 'dynamodb:EnclosingOperation': ['TransactWriteItems'] } } }));
  }
}
