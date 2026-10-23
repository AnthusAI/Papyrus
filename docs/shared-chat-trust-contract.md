# Site-hosted shared chat trust contract

This is a code-local contract for a future Papyrus site-hosted shared chat API. It is not an HTTP route, JWT verifier, production auth implementation, or change to the current AppSync send path. The newsroom console continues to send and persist through its existing Papyrus/AppSync adapter.

## Host boundary

The hosting server supplies `verifyCredential`, `resolveMembership`, and `resolveTranscriptOwner` to `lib/shared-chat-admission.ts`. The first callback must validate the credential's cryptographic signature and token validity with the configured Papyrus user pool, then return verified claims. It must not accept a principal object supplied by a browser. This module independently checks the returned issuer, time claims, configured audience rule, and explicitly configured `token_use` values. Tests inject fakes; they do not make those fakes production authentication.

The host profile pins one issuer and a site identifier from server configuration. Membership lookup takes the verified `sub` and configured site and returns the authoritative Account and editor membership. Request body identity fields are treated only as consistency hints; mismatches are rejected. Channel ownership is checked against `(accountId, siteId, editorSub, channelId)` on each admitted message. The default denies cross-editor transcript access, including admin access; that policy needs a separate decision before broadening it.

## JWT profile is a deployment input

Do not infer the token kind from the fact that the app uses Cognito. Configure the accepted `token_use` only after verifying the actual Papyrus browser request and server contract. The trust profile requires an explicit, nonempty accepted-token-use list and an explicit audience rule.

JWT `aud` and Cognito `client_id` are different claims. For an ID token, `aud` normally identifies the app client; for an access token, `client_id` identifies the app client and `aud` may be absent unless a resource audience is configured. The code therefore makes the host select either an `aud` equality rule or a `client_id` equality rule; matching one claim never silently substitutes for the other. Confirm the real token type, issuer, expected app client/resource audience, `token_use`, and expiry behavior before wiring the host verifier.

The injected verifier must validate JWT signature using trusted JWKS, issuer, algorithm, expiry and not-before constraints. The admission layer repeats issuer and temporal checks over the returned claims with bounded configured clock skew. Production adapter configuration, JWKS refresh behavior, IAM/OIDC grants, and deployment are intentionally outside this contract.

## Idempotency

The host derives idempotency scope from the server-side owner tuple, channel, and operation. A stable opaque key plus the same canonical payload must return the original result; reusing the key with a changed payload must conflict. A key is never authorization. `ChatIdempotencyStore.executeOnce` must be implemented with an atomic durable primitive before production use; the test fake is in-memory and must not be reused by a server.

## Verification

`npm run test:shared-chat-admission` covers rejection of wrong issuer/audience/token use, expired or not-yet-valid credentials, missing credentials, inactive/nonmember identities, client-supplied identity mismatches, and another editor's transcript. It also checks same-key replay, changed-payload conflict, and editor-scoped key isolation. The shared-chat Gherkin feature invokes this hermetic contract suite alongside the existing UI scenarios. None of these tests contacts Cognito, AppSync, AWS, or a deployed chat service.
