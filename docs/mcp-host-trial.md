# ChatGPT MCP host trial

This is a trial plan, not evidence of a completed host test. No account has been configured and no package has been uploaded as part of these checks. Use an explicitly authorized test site and test records after the normal site release. The server's [configuration and limits](mcp.md) and [OAuth contract](mcp-oauth.md) apply.

## Prerequisites and registered public client

The host needs a reachable HTTPS console origin with the MCP endpoint and every discovery and OAuth route forwarded to the CMS. Configure the site's OAuth client allowlist with a chosen public client ID and the **exact** callback URI shown by the ChatGPT connection. The current OAuth implementation advertises RFC 9207 issuer identification and returns the issuer with authorization responses; the [OpenAI authentication guide](https://developers.openai.com/plugins/build/auth) describes when ChatGPT uses its stable callback. Confirm the actual callback in the connection rather than substituting one from an example. A separate public origin currently prevents reader consent; use the same canonical origin for a reader trial.

For a packaged plugin using an already registered public client, the following illustrates the relevant `mcp.json` structure from the [OpenAI packaging reference](https://developers.openai.com/plugins/build/plugins#configure-mcp-authentication). Replace both placeholders with the site's values. This is an example to prepare and review, not an uploaded or validated package; any surrounding `plugin.json` and assets still need their own validation.

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "papyrus": {
      "type": "streamable-http",
      "url": "https://cms.example/api/mcp",
      "extensions": {
        "com.openai": {
          "auth": {
            "type": "oauth",
            "client": {
              "mode": "provided",
              "clientId": "papyrus-trial",
              "tokenEndpointAuthMethod": "none"
            }
          }
        }
      }
    }
  }
}
```

Do not include a client secret, bearer token, or account credentials in the package. The example uses discovery and no requested scopes; do not assume that a custom-server connection form offers the same settings as a packaged plugin. Papyrus does not implement dynamic registration or Client ID Metadata Document registration. If the host cannot configure a provided public client, record that as a host compatibility blocker rather than weakening the server. See the [OpenAI submission authentication instructions](https://developers.openai.com/plugins/deploy/submission#configure-authentication-for-submission).

## Checks available without a site

Run `npm run test:mcp-integration`, `npx cucumber-js --profile mcpTransport`, `npx cucumber-js --profile mcpOAuth`, and `npx cucumber-js --profile mcpCards`. The integration harness uses real HTTP Request/Response objects with a fake OAuth verifier and fake private tool service. The card profile runs a local Playwright host fixture. These checks cover protocol, authorization boundaries, optional Apps and browser origins, card navigation, stale updates and failure responses; they do not prove ChatGPT interoperability or exercise AWS, real consent, or real publication data. The focused CI job runs these profiles with the Python grant and domain tests. Bundling can be synthesized without AWS using `scripts/verify-mcp-bundle.ts` with `MCP_TEST_OUTPUT` set; test both checkout and installed-wheel modes on Linux ARM64 to execute the actual native dependencies.

## Trial on a configured HTTPS site

1. With a test staff identity, verify an unauthenticated POST to `/api/mcp` returns a 401 challenge pointing to `/api/mcp/oauth/resource`; check that this metadata identifies the configured console origin and the same issuer appears in authorization-server metadata. Check that S256 and the public token authentication method are advertised. Do not record tokens or authorization codes.
2. In ChatGPT on the web, follow the current [custom MCP server instructions](https://developers.openai.com/api/docs/guides/custom-mcp-server) for the authorized test connection, selecting OAuth and the provided public client where the chosen flow supports it. Confirm the callback shown by that connection matches the exact allowlist entry. Complete sign-in and consent, including a denial and retry. Verify the connection lists only tools the staff identity can use.
3. In a new chat, explicitly ask the host to use `story_get` for a known test Story. Check text and structured results. With Apps enabled, confirm the Story card renders, navigation and a permitted action use the same Story, and a stale revision prompts refresh before retry. A publish gate must never gain an answer control. Without Apps, verify the text result remains usable.
4. Repeat with a reader identity on a same-origin site. Confirm discovery contains only permitted reader tools and that a staff call is rejected. Reader writes remain subject to the site's production reader switch; do not enable or bypass it to make this trial pass.
5. Verify expired, revoked, wrong-resource and wrong-identity grants cannot obtain data; confirm an unavailable verifier gives a service failure and never exposes tools. If allowed in the test environment, exercise refresh and reconnect, then remove the test connection according to its normal lifecycle. Record observed status, connection mode, tool names, fixture IDs and the result, without secrets.

The local fixture covers a subset of MCP Apps bridge messages. Real ChatGPT initialization, tool metadata interpretation, authorization redirects, OAuth refresh, and iframe behavior remain unverified until this trial is actually run. `resources/read` and rendering alone do not establish that a particular host accepts the package or selects the App.
