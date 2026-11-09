# Vendored packages

## `@anthus/cost-accounting` 0.1.0

The Prospectus cost-accounting package (Prospectus `packages/cost-accounting`, model in Prospectus `docs/COST_ACCOUNTING.md`).

- Built from AnthusAI/Prospectus `develop` at `3eaedd6` (after AnthusAI/Prospectus#148 and #149, which added account `"owner"` to tags and to usage messages), with `npm run build && npm pack`.
- `anthus-cost-accounting-0.1.0.tgz` sha256: `e8621e7f75fa91dd8eb30ad23880fce96b0741be1610228cc10d87176e157303`

The published `@anthusai/papyrus` package cannot depend on a local tarball, so the package's TypeScript sources are copied where each part of Papyrus compiles them:

- `amplify/vendor/anthus-cost-accounting/{tags,cdk}.ts`, used by the site backend.
- `infra/amplify-app-shell/lib/cost-accounting-{tags,cdk}.ts`, used by the app shell, which is published flat under `@anthusai/papyrus/infra`.

The only change from the upstream sources is the relative import path (`./tags` or `./cost-accounting-tags` instead of `./tags.js`). `scripts/test-cost-tags.ts` checks the tarball's sha256 against this file and that the two copies agree.

The package's TypeScript usage sender (`usage.ts`) is not vendored: Papyrus's model calls run in Python, which uses its twin, `src/papyrus_cost_usage`.

To update: build and pack the package from a Prospectus checkout, replace the tarball, copy `src/tags.ts` and `src/cdk.ts` to both places with the import adjusted, and record the commit and sha256 here.
