import assert from 'node:assert/strict';
import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { Code, Function as LambdaFunction, Runtime } from 'aws-cdk-lib/aws-lambda';
import { addMcpTools, mcpBrowserOptions, readerPublication } from '../amplify/mcp-tools/resource';
const app = new App(); const stack = new Stack(app, 'Test', { env: { account: '123456789012', region: 'us-east-1' } });
const reader = new LambdaFunction(stack, 'Reader', { runtime: Runtime.PYTHON_3_12, handler: 'index.handler', code: Code.fromInline('def handler(event, context): pass') });
addMcpTools(stack, { origin: 'https://cms.example', invokerRoleArn: 'arn:aws:iam::123456789012:role/site-compute' }, { endpoint: 'https://graphql.example/graphql', tenant: '', publication: readerPublication('https://public.example'), reader, referenceSingleTenant: true }, Code.fromInline('def handler(event, context): pass'));
const template = Template.fromStack(stack);
template.hasResourceProperties('AWS::Lambda::Function', { Handler: 'handler.handler', Environment: { Variables: { PAPYRUS_GRAPHQL_ENDPOINT: 'https://graphql.example/graphql', PAPYRUS_MCP_STORY_DRAFT_ENABLED: 'true', PAPYRUS_PUBLICATION_ID: 'public.example', PAPYRUS_READER_STEERING_FUNCTION: Match.anyValue(), PAPYRUS_MCP_REFERENCE_SINGLE_TENANT: 'true' } } });
template.hasResourceProperties('AWS::Lambda::Permission', { Action: 'lambda:InvokeFunction', Principal: 'arn:aws:iam::123456789012:role/site-compute' });
template.hasResourceProperties('AWS::IAM::Policy', { PolicyDocument: { Statement: Match.arrayWith([Match.objectLike({ Action: 'lambda:InvokeFunction', Resource: Match.anyValue() })]) } });
assert.equal(readerPublication(undefined), ''); assert.equal(readerPublication('https://example.test/path'), ''); assert.equal(readerPublication('http://example.test'), '');

assert.deepEqual(mcpBrowserOptions({}), { appsEnabled: false, allowedOrigins: [] });
assert.deepEqual(mcpBrowserOptions({ PAPYRUS_MCP_APPS: 'true', PAPYRUS_MCP_ALLOWED_ORIGINS: 'https://one.example,https://two.example' }).allowedOrigins, ['https://one.example', 'https://two.example']);
for (const bad of ['*', 'http://one.example', 'https://one.example/path']) assert.throws(() => mcpBrowserOptions({ PAPYRUS_MCP_ALLOWED_ORIGINS: bad }));
