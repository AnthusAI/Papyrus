# Spike PPY-867f76: tenant claims and owner rules

Throwaway. Nothing here is imported by the app. Findings: `docs/plans/tenant-claims-spike-1.md`.

- `schema.ts`: Item, Reference, ItemLocked with claims-only `ownerDefinedIn("tenantId").identityClaim(...)` rules.
- `pre-token/index.js`: the V2 pre-token-generation Lambda with a hard-coded membership table.
- `synth.ts`: synthesizes the schema plus the Cognito trigger (V2_0) with the CDK. No AWS calls, no deploy.
- `run-scenarios.cjs`: runs the generated VTL resolvers against an in-memory table.

```
npx tsx spikes/tenant-claims-1/synth.ts <outdir>
mkdir <simdir> && (cd <simdir> && npm init -y && npm i amplify-appsync-simulator@2)
SIM_DIR=<simdir> node spikes/tenant-claims-1/run-scenarios.cjs <outdir>
```

The sandbox run (features_backend/tenant-claims-spike.feature, @sandbox) is still to do by hand:
`docs/aws-sandbox-personal.md`, then `ampx sandbox` with this schema and the Lambda wired as in `synth.ts`.
