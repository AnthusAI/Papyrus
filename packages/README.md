# Package skeletons (origin: spike PPY-82be6c)

Proof-of-approach for `docs/standard-site.md` section 1.3/1.4. **Both packages are published**: `@anthusai/papyrus` on npm and `papyrus-newsroom` on PyPI, released in lockstep by semantic-release when `develop` or `main` is pushed (see `docs/releasing.md`).
The Papyrus repo root is unchanged as an app; packages are assembled from it.

```bash
# needs `build` for Python and a TypeScript install to compile the backend JS
PAPYRUS_PYTHON=/path/to/venv/bin/python \
PAPYRUS_TS_RESOLVE_FROM=/path/with/node_modules/typescript \
  node packages/stage.mjs --version 0.1.0-next.2     # -> dist-packages/
```

Outputs in `dist-packages/`: `anthusai-papyrus-<v>.tgz` (the only npm tarball),
`papyrus_newsroom-<pep440>-py3-none-any.whl` (+ sdist). semver `X.Y.Z-next.N` maps to PEP 440 `X.Y.Z.devN`.

| Piece | File |
| --- | --- |
| npm `@anthusai/papyrus` (stage + pack) | `packages/papyrus/scripts/stage.mjs`, `package.template.json` |
| `withPapyrus()` | `packages/papyrus/src/with-papyrus.mjs` |
| `papyrus-app sync` (route shims, `middleware.ts`) | `packages/papyrus/src/sync.mjs`, `bin/papyrus-app.mjs` |
| `papyrus-app brand diff <id>` (site `publication/` vs the reference pack in a Papyrus checkout) | `packages/papyrus/src/brand.mjs` |
| `defineSiteBackend(site)` | `amplify/site-backend.ts` (exported via `@anthusai/papyrus/backend`) |
| Python Lambda bundling from the wheel | `amplify/functions/shared/python-bundle.ts` |
| `@anthusai/papyrus/infra` (CDK constructs, optional peers) + `papyrus-infra` bin | stage step in `packages/papyrus/scripts/stage.mjs`, `bin/papyrus-infra.mjs` |
| `defineSite()`, `papyrus-site` alias | `lib/define-site.ts`, `papyrus.config.ts`, `tsconfig.json` paths |

## Amplify builds only deploy

CI (type-check, lint, tests) runs in GitHub Actions for public repos and locally for private ones, never in Amplify: Amplify build minutes cost money and `next build`'s "Linting and checking validity of types" step ran out of memory there. When `withPapyrus` sees the variables Amplify sets during a build (`AWS_APP_ID` or `AWS_BRANCH`) it defaults `typescript.ignoreBuildErrors` and `eslint.ignoreDuringBuilds` to `true`. A site's own values for those keys win. Outside Amplify (local, GitHub Actions, `scripts/check-consumer-site-typecheck.mjs`) the checks run as before. To debug a type error in Amplify, set `PAPYRUS_NEXT_BUILD_CHECKS=1` in the app's environment variables. Verified by `npm run test:with-papyrus-build-checks` and `features/with-papyrus-build-checks.feature`.

## Brand packs are site-owned

The npm package ships no publication code (staging refuses to), so a site's `publication/` brand pack is its own copy of a pack like `publications/anth_us/` and `papyrus-app sync` never touches it. Nothing upgrades it either, so it can fall behind the reference pack (a new logo component, CSS or font). After upgrading Papyrus, run `papyrus-app brand diff <brand-id> [--papyrus ../Papyrus]` from the site: it lists files the reference gained, files that differ (imports are normalized, so only real differences show) and site-only files, and exits 1 on drift. Site-specific edits, such as `readerDeployment`, are expected to appear as differences.
