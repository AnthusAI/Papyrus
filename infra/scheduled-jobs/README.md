# Scheduled container jobs (CDK)

Generic EventBridge Scheduler + Step Functions + Fargate construct (`lib/scheduled-container-job.ts`), the weekly
knowledge-run pipeline built on it (`lib/knowledge-pipeline.ts`), and the shared projection lease table
(`lib/projection-lock-stack.ts`). Behaviour: `features/scheduled-container-job.feature`, executed by
`npm run test:scheduled-job-synth` from the repository root.

Per-publication settings are the optional `knowledgeRun` block of the publication's `infra/site.json` (schema in
`lib/knowledge-run-config.ts`; example: `../amplify-app-shell/examples/shipped.site.json`). The e-mail for alarms is
read at deploy time from the SSM String parameter named by `knowledgeRun.alarmEmailParameter`
(default `/papyrus/<site>/knowledge-run/alarm-email`); create it first.

```bash
cd infra/scheduled-jobs && npm ci
export AWS_PROFILE=papyrus-production          # account 712236451410; check with `aws sts get-caller-identity`
SITE=../amplify-app-shell/examples/shipped.site.json
npx cdk synth  -c site=$SITE -c imageTag=<tag>
npx cdk diff   -c site=$SITE -c imageTag=<tag>
npx cdk deploy ProjectionLock                                   # once per account, before any job stack
npx cdk deploy KnowledgeRun-shipped -c site=$SITE -c imageTag=<tag>
```

Run a stage chain by hand with an execution name starting `manual-` (or `test-` to honour `failStage`):
`aws stepfunctions start-execution --state-machine-arn <StateMachineArn> --name test-1 --input '{"publication":"shipped"}'`.
