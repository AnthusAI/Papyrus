const { Given, When, Then } = require('@cucumber/cucumber');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const path = require('node:path');
let checks;
const run = () => checks ??= promisify(execFile)(process.execPath, ['--import', 'tsx', 'scripts/test-mcp-integration.ts'], { cwd: path.resolve(__dirname, '../..') });
for (const step of ['a configured site with a seeded staff story', 'a configured site with a verified reader', 'a site with incomplete MCP configuration', 'a configured site with exact browser origins and Apps enabled']) Given(step, function () {});
for (const step of ['a verified staff client lists and calls the story tool', 'the reader lists tools and calls a staff tool', 'a browser from an allowed origin connects and another origin tries to connect', 'a verified staff client saves a draft']) When(step, function () {});
for (const step of ['chat receives text and structured data and the App receives its resource', 'the private credentials are not returned to the client', 'only reader tools are available', 'MCP is unavailable', 'an invalid token is challenged while an unavailable verifier returns service unavailable', 'only the allowed origin receives browser access', 'disabling Apps hides their resources', 'the authorized tool list is reused for the response']) Then(step, async function () { await run(); });
