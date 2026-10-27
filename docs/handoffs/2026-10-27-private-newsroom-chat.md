# Private newsroom chat engineering closeout

Engineering ownership ended at the user's request on October 27, 2026. No further implementation or deployment is scheduled by this owner.

## Delivered and verified

- Existing authorized p.apyr.us newsroom login opens private chat without a second Prospectus connection. The approved contract verifies the configured Cognito issuer, app client, expiry and editor/admin authority, derives the publication namespace from trusted server configuration, and isolates history by issuer/subject. No automatic access to Prospectus data, tools or legacy transcripts.
- One separately labelled production test received a real model reply at10:11AM America/New_York. Reply and user message survived reload. Its turn completed in one attempt with no recovery. The user independently confirmed a production response at11:19AM, reported by the parent task.
- Mobile390×844 Chrome viewport: integrated Chat navigation, open, close, reopen and browser Back passed with retained history. Anonymous transcript access returned401.
- Earlier failed test remained intact with terminal reason `recovery attempts exhausted`. It was not reset, deleted or replayed with a guessed idempotency key. The successful test was explicitly separate.

## Source and deployed state

- Newsroom identity fix: PR754, merged `dd35bc9427b22994443ea5f80ceb1683e50a237e`, released5.41.6. Mobile navigation correction: PR748, released5.41.4. Cumulative5.41.8 preserves both.
- Exact IAM correction: PR774, reviewed head `51076c7cb56d756b97374a1530cfb7052ea0dfbd`, merged into develop as `21969547b145803f5fc9058ecf6e978b1ead46a5`. Both CI jobs passed in40519581045; local shared-chat21scenarios/69steps and both template validators passed.
- Stack `PapyrusChatDataCandidate`, account712236451410/us-east-1, change set `chat-condition-check-20261027`: UPDATE_COMPLETE,24resources. Only `dynamodb:ConditionCheckItem` added for existing gateway→messaging table and run-worker→conversation table. No indexes, wildcards, probe grants, new roles, credentials or Prospectus grants.
- Both worker hashes remain `nV7KH+JJs+MX7FZ1pBUyAMDu2BXfqiPKy4myLTU0k14=` and both mappings Enabled. The approved existing model parameter is configured; no secret value is included here.
- After cumulative site5.41.8 deployed as `59e944a1fd3c67d16796b783c66bdbf49b4c8228`, Amplify87 SUCCEED, both exact live IAM grants and the complete candidate template remained intact. This did not require a separate chat package release.
- Site PR88 was superseded by cumulative pins and intentionally remained unmerged. Do not merge its older5.41.6 pin over the current site.

Do not deploy the checked-in review candidate wholesale over the activated stack: preserve live mappings, parameters and verified worker assets. The source correction deliberately retained existing asset keys.

## Remaining validation and broader scope

Physical iPhone Safari/keyboard behavior was not tested. Cross-editor/publication isolation, wrong issuer/client, expiry and identity-change behavior passed controlled regressions; a live second-editor isolation test was not performed. These are evidence limits, not claims that those live checks passed.

PPY-0d18a6 is closed for this delivered scope. M3 PPY-7962e3 and M6 PPY-839cf7 retain their broader open status with milestone comments. Slack migration, removal of all legacy responder code, legacy-history migration, skills/procedures and arbitrary editorial tools are not completed by this delivery. The old temporary/global Prospectus administration proposals were never implemented and must not be revived as an approved plan.

## Handoff and preservation

Branch `board/PPY-0d18a6-chat-closeout` contains this document and Kanbus closeout events. All chat worktree source heads were checked against their remote branches before removal. Shared primary checkouts, predecessor task6 worktrees and uncertain ownership remain untouched. Newsletter owner confirmed no dependency on the chat node_modules target.

Detailed local acceptance evidence and screenshots remain in `/Users/home/Documents/Codex/2026-10-26/task/`, including `chat-live-acceptance-result.md`, `chat-condition-deployment-result.json`, and the reply/mobile screenshots. They are not copied into the repository because they contain live newsroom context. Ignored local configurations and generated untracked test bundles are preserved locally during cleanup, not published. No secrets or browser credentials are part of the handoff commit.
