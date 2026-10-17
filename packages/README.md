# Package skeletons (SPIKE, PPY-82be6c)

Proof-of-approach for `docs/standard-site.md` section 1.3/1.4. **Nothing here is published.**
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
| `defineSiteBackend(site)` | `amplify/site-backend.ts` (exported via `@anthusai/papyrus/backend`) |
| Python Lambda bundling from the wheel | `amplify/functions/shared/python-bundle.ts` |
| `@anthusai/papyrus/infra` (CDK constructs, optional peers) + `papyrus-infra` bin | stage step in `packages/papyrus/scripts/stage.mjs`, `bin/papyrus-infra.mjs` |
| `defineSite()`, `papyrus-site` alias | `lib/define-site.ts`, `papyrus.config.ts`, `tsconfig.json` paths |
