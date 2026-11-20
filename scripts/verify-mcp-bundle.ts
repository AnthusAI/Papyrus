/** Synthesizes the real asset; caller selects checkout or pip mode with environment. */
import { App, Stack } from 'aws-cdk-lib';
import { addMcpTools } from '../amplify/mcp-tools/resource';
const outdir = process.env.MCP_TEST_OUTPUT;
if (!outdir) throw new Error('MCP_TEST_OUTPUT is required');
const app = new App({ outdir });
const stack = new Stack(app, 'McpBundle');
addMcpTools(stack, { origin: 'https://cms.example', invokerRoleArn: 'arn:aws:iam::123456789012:role/site-compute' }, { endpoint: 'https://api.example/graphql', tenant: '', publication: '' });
app.synth();
