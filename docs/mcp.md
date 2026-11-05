# Site MCP service

MCP is off by default. A site may opt in with `backend.features.mcp: true` or `PAPYRUS_ENABLE_MCP=true` in its backend build. This provisions a private grant store and tools Lambda for that site. It does not change a shared stack. Enable a site only after its backend and CMS runtime have all the configuration below; do not use a deployment to test the feature.

## Configuration

Set these site-specific values in the appropriate backend build and CMS runtime configuration:

- `PAPYRUS_CONSOLE_ORIGIN`: the exact HTTPS origin serving the CMS and `/api/mcp`, without a path or trailing slash. `PAPYRUS_SITE_ORIGIN` is the fallback when the console origin is not set. The origin is configured, never inferred from an incoming Host header.
- `PAPYRUS_SITE_ORIGIN`: the exact HTTPS public site origin. When reader steering is enabled, its host identifies the publication sent to reader actions. A missing or invalid public origin leaves reader tools unavailable. This origin can differ from the console origin.
- `PAPYRUS_MCP_INVOKER_ROLE_ARN`: the IAM role ARN of this site's CMS compute role. Only that role is granted permission to invoke the private grant and tools functions. The tools function can invoke the reader-actions function only when the reader-steering plugin and a public origin are configured.
- `PAPYRUS_MCP_OAUTH_CLIENTS`: a JSON object mapping registered public client IDs to arrays of exact redirect URIs, for example `{"client-id":["https://client.example/callback"]}`. Set it in the CMS runtime as well as any build environment that exports runtime variables. Unconfigured or invalid clients leave MCP unavailable. Client secrets and dynamic registration are not supported.
- `PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER`: the SSM SecureString parameter containing the existing Prospectus session sealing secret; the runtime must be able to read it. Never put the value in configuration files or a repository.
- Optional `PAPYRUS_MCP_APPS=true` exposes the Reference and Story App resources. It defaults to false; ordinary text and structured tool results remain available.
- Optional `PAPYRUS_MCP_ALLOWED_ORIGINS` is a comma-separated list of exact HTTPS browser origins, for example `https://client.example,https://another.example`. There are no browser origins by default; wildcards, paths and HTTP are rejected. Native clients without an Origin header do not need this list.
- Optional `PAPYRUS_TENANT_ID` scopes the user-pool client to the site's tenant. Reference tools are currently hidden for tenant-scoped sites. On a verified single-tenant backend, `PAPYRUS_MCP_REFERENCE_SINGLE_TENANT=true` enables Reference decisions only when the same opt-in is applied to category-action. Leave it off otherwise.

The protected resource is `<console-origin>/api/mcp`; its challenge points to `<console-origin>/api/mcp/oauth/resource`. OAuth metadata and browser authorization, consent, token and revocation routes are under `/api/mcp/oauth/`. OAuth clients use authorization code with PKCE S256 and registered redirects. Staff use the site's Google/Cognito session, and readers use a valid Prospectus site subject. A reader write remains subject to the reader-steering production switch and policy. A CMS behind an edge distribution must forward `/api/*` to the CMS without rewriting the configured host, authorization headers or OAuth query parameters. In particular, use the console origin for discovery even when public pages use a different origin.

## Verification and limits

Run `npm run test:mcp-integration` locally for seeded staff and reader protocol, access, disabled-state, App and infrastructure checks. Run the other MCP transport, OAuth and domain checks in CI; these use fakes and make no AWS calls. To check a configured site after its normal release, use a registered client to discover the protected resource, complete consent, list tools and read a permitted record. Verify an unauthenticated call is challenged and a reader cannot call a staff tool. Do not include bearer tokens or private identity claims in logs or reports.

The implementation is stateless Streamable HTTP: POST requests and notifications are supported; a server event stream and session resumption are not. The tool list is capability-based and is narrower than the full domain vocabulary. Initial staff capabilities include Story reads and versions, evidence, Reference reads and conditional decisions when configured; reader capabilities are submit and comment when available. Discover the actual list for the signed-in identity. App cards are optional and clients without App support use the text and structured results. No production integration or live host interoperability test is implied by the seeded checks.
