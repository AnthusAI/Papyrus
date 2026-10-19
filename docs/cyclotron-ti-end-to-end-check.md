# Threat Intelligence end-to-end check for delegated approval

Needs the TI deploy to include Papyrus 1.12.1 or later, and a sign-in as Ryan (only a signed-in person can approve a delegation; no agent can do that step, and no secret is ever pasted anywhere). Run on the Mac, where the AWS credentials and the TI steering config are.

1. Confirm the deploy: the TI newsroom (https://threat-intelligence.anth.us/newsroom) shows the delegations screen with pending requests and an Approve button (Papyrus 1.12.1 or later plus the device-authorization release).
2. On the Mac run: papyrus references request-delegation --agent e2e-check --hours 1 --wait
   It prints a code like XXXX-XXXX and keeps the secret in a 0600 token file (its path is printed). It waits for approval. Ryan opens the Delegations screen, sees e2e-check with that code, and presses Approve. Nothing is pasted. The command ends when the request is approved, denied or expired.
3. Pick a pending test Reference id (a Reference you do not mind marking). Run, using the token file path from step 2:

   papyrus references approve --reference <record id> --on-behalf-of <Ryan's sign-in email> --agent e2e-check --delegation-file <token file path> --instruction "e2e check: approve this test reference" --note "end to end check"

   Expect output containing "on behalf of".
4. Read it back: open the Reference in the newsroom and confirm the curation shows as Ryan's, relayed by e2e-check, with the instruction quoted.
5. Wrong-agent check: rerun step 3 with --agent someone-else. Expect a refusal.
6. Revoke the delegation in the screen, rerun step 3. Expect a refusal.
7. Run a sweep with --apply on TI (dry run first) and confirm `retiredLabels`, the live agreement `loop` and `autoDecision` fields appear in the shadow-agreement payload.

Also check the unapproved case: run request-delegation without --wait and try step 3 with its token file before Ryan approves. Expect a refusal (not approved).

Pass means steps 3 to 6 behave as described. Then post docs/story-reporting.md's section and /mnt/project-files/cyclotron-priming/chatgpt-test-prompt.md to Ryan's ChatGPT session.
