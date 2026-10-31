---
name: editorial-copyedit-cycle
description: >
  Copy-edit Papyrus articles against the site's editorial policies with Humanus:
  `papyrus editorial check` (rule and judgment lanes), `papyrus editorial suggest`
  (rewrite options), a person's choice, then a new Papyrus version and, when
  authorized, a publish. Use when someone asks to check, lint, proofread or
  copy-edit a draft or recently published articles, to find AI-writing tells or
  claims that break house rules, or for rewrite options for a passage. Findings
  and options are advice; apply only what a person chose.
---

# Editorial copy-edit cycle

Articles live in the site's **newsroom backend** (AppSync and DynamoDB in AWS),
not in Git. A site repository holds settings only. If a site repository still
has a content folder or submodule, it is stale: editing it changes nothing on
the site. Read a site repository's AGENTS.md from `origin/main` after a fetch,
never from a local checkout that may be behind.

Papyrus keeps the publication's editorial policies in the CMS (Administration →
Editorial checks: `EditorialPolicy`, `EditorialCheckSettings`). Humanus checks
text against them in two lanes: **rule** policies (phrases, patterns, built-in
checks) and **judgment** policies, which a decision model (TypeSafe Jev) answers
sentence by sentence with a probability. Editors see the same findings in the
article editor.

## Before you start

- **Connect to the site.** Use the publication's configured editorial session
  (`papyrus login <site>`). The explicit IAM operator lane is
  `PAPYRUS_GRAPHQL_AUTH=iam` with `AWS_PROFILE=papyrus-production`, plus
  `PAPYRUS_SITE_ROOT` pointing at a folder holding the deployed backend's
  `amplify_outputs.json`. `scripts/connect.sh <workdir> <amplify-app-id>` builds
  that file from the main-branch backend stack and prints the exports. Choose IAM
  deliberately; never fall back to it after a failed user session. IAM signing
  needs `boto3`, and saving versions needs the `papyrus-newsroom[markus]` extra.
- **Load context and policies** before editing:

  ```bash
  papyrus editorial context --backend cloud --section SECTION_ID --format json
  papyrus editorial pack --section SECTION_ID
  papyrus editorial policies list
  ```

  Omit `--section` for publication-wide work, or use the context command's
  `--story`/`--assignment` selector to resolve the section. Doctrine and Humanus
  rule controls complement each other; load both. Keep the context hash and
  source revisions privately. Missing, denied, conflicting or ambiguous required
  context stops the pass; do not substitute seed YAML.
- Keep doctrine, policy examples, model prompts and editorial reasons private.
  Do not copy them into public source, fixtures, issues, logs, feeds or reader
  content. Synthetic test guidance is fine in public tests.
- **Keys**: `TYPESAFE_API_KEY` for judgment policies and `OPENAI_API_KEY` for
  rewrite options. Load them into the command's environment only; never print
  them. A 401 `token_invalidated` means the key was revoked. Say so, and tell the
  person which `.env` needs a new key. Test both before the pass, not forty
  minutes in: run one `check` and one `suggest` on a short draft first.
- Know the article's section: section policies replace publication controls with
  the same key.

## The cycle

1. **Choose the articles.** For one draft, use the file you were given. For a
   pass over published work, list the newest items on the site (or as asked) and
   fetch each one's current version read-only:
   `scripts/fetch_current.py <outdir> <slug>…` writes `<slug>.md` (the
   `bodyMarkus`) and an `index.json` of lineage, current version id and stage.
   Keep these originals unchanged; edit copies.

2. **Check** (read-only):

   ```bash
   papyrus editorial check --draft draft.md --section <section> > check.json
   ```

   Each finding has `policyId`, `detectorId`, `severity` (`error`/`warn`/`info`),
   `status` (`violation`, or `review` when the model is unsure), `message`,
   `excerpt`, `span` (UTF-16 offsets) and, for judgment policies, `probability`.
   **Read `lanes`.** `classifier.detectors: 0` means the site has no judgment
   policies, so voice, claims and accuracy questions were not asked at all. Say
   so instead of reporting a clean result, and offer to draft judgment policies
   (step 7).

3. **Triage.** Rule lanes over-report on technical, data-heavy prose. Before
   showing anything to a person, drop findings that are:
   - terms of art the article defines, flagged as vocabulary;
   - inside quotations, code, URLs, link targets or worked examples;
   - contractions that cannot happen (a phrase ending a sentence: "as it is",
     "how sure it is"), or matches of the wrong sense ("there" as a place,
     "let us" meaning "allowed us");
   - passive voice where the actor is unknown or deliberately left out;
   - generic repetition, missing-attribution or certainty detectors firing on
     numbers the article itself measured.
   Keep: house voice and banned phrases, intensifiers and filler, passive voice
   where the actor is "we" and known, and judgment violations. When you drop a
   whole class, report the counts **and propose the policy change that would stop
   it next time**: an `exceptions` entry for a term of art, a severity change, or a
   narrower judgment question. That's how site knowledge reaches the policies
   instead of staying in one agent's head. A person approves policy changes.

4. **Suggest** for the findings worth fixing, or for any passage:

   ```bash
   papyrus editorial suggest --draft draft.md --finding-id f-0123456789abcdef --note "shorter"
   papyrus editorial suggest --draft draft.md --select "Exact passage from the draft."
   ```

   The finding must come from the unchanged draft. A finding is rewritten as
   its whole sentence. Options never add facts; `factVerificationRequired: true`
   means an option changes a claim. If suggestions are unavailable, you may write
   options yourself from each policy's rewrite guidance. Say that you did.

5. **Choose.** Show a table (article, current text, proposed text) and apply
   only what the person accepts. Do not resolve `review` findings on your own.
   The person may approve a class of fix ("every present-tense production claim,
   in past tense"). Apply that class, then show the result.

6. **Apply and check again.** Make exact-string replacements on the copies,
   each asserted to match exactly once, so a drifted original fails loudly.
   Re-run both lanes on the copies: the targeted findings should be gone and
   nothing new should appear. Finding ids stay the same for unchanged sentences.
   Re-read every sentence whose tense or subject you changed, for agreement.

7. **Judgment policies a site lacks.** Propose them; do not keep them in a
   skill or a repository. Write a Humanus `policy-pack-v1` file with
   `lane: classifier` detectors (one yes/no question per policy, sentence scope,
   `threshold` 0.8, `reviewAt` 0.5), or draft questions with
   `humanus draft-questions`. Try it locally with
   `humanus check --draft draft.md --pack candidate.json` and show the person the
   hits. Only after approval, add it to the site:
   `papyrus editorial policies add --file candidate.json --dry-run`, then without
   `--dry-run`.

## Save and publish

- **Save** each edited article as a new version. The original version is kept,
  and the front matter carries over:

  ```bash
  papyrus stories save-version --story <lineage> --body-file new/<slug>.md \
    --reason "<what changed; who approved>" --author-label "AI" --dry-run
  ```

  `save-version` writes unless `--dry-run` is passed. Run the dry run first, then
  the real save. Every save checks the new version. If that check fails (for
  example an authorization error under IAM), the save still stands. Re-run
  `papyrus editorial check-version --item <lineage>-vN` from a signed-in session.
- **Publish** only when a person authorized publishing these edits. Copy editing
  never publishes as a side effect:

  ```bash
  papyrus ops content publish --id <lineage>-vN --dry-run
  papyrus ops content publish --id <lineage>-vN
  ```

  Publishing re-renders the site's pages for that item. `image-missing` means
  the version has no media row for an image its body uses. Report it; do not
  hand-edit `MediaAsset` rows.
- **Verify**: fetch the live page and look for an edited sentence. Check the
  version list with `papyrus stories versions --story <lineage>`.
- **Roll back**: save the previous version's body as a new version and publish
  it.

## Policies

- `papyrus editorial pack [--section <section>]` prints the composed policy pack.
- `papyrus editorial import --profile publications/<pub>/style-profile.yml`
  turns a legacy style profile's lexicon, banned phrases, patterns, checks and
  guidance into publication policies (`--replace` overwrites policies with the
  same key).
- `papyrus editorial policies add --file pack.json [--dry-run]` creates or
  versions policies from a policy pack, including judgment questions.
- New policies, the AI-writing tells starter pack, drafted judgment questions and
  recalibration from editors' decisions are also in Administration → Editorial
  checks.

Never loosen a policy (disable it, raise a threshold) to make a draft pass;
report the conflict instead.
