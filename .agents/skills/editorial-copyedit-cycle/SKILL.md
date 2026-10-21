---
name: editorial-copyedit-cycle
description: >
  Copy-edit a Papyrus article against the site's editorial policies with
  `papyrus editorial check` and `papyrus editorial suggest` (Humanus). Use when
  someone asks to check, lint or copy-edit a draft, wants the AI-writing tells
  found, or asks for rewrite options for a passage. Findings and options are
  advice; apply only what a person chose.
---

# Editorial copy-edit cycle

Papyrus keeps the publication's editorial policies in the CMS (Administration →
Editorial checks: `EditorialPolicy`, `EditorialCheckSettings`). Humanus checks
drafts against them: rule policies (phrases, patterns, built-in checks) and
judgment policies, which a decision model (TypeSafe Jev) answers sentence by
sentence with a probability. Editors see the same findings in the article
editor, marked in the markup and on the preview.

## Before you start

- Use the publication's configured authenticated editorial session. Read current
  doctrine and the selected section overlay before editing:

  ```bash
  papyrus editorial context --backend cloud --section SECTION_ID --format json
  papyrus editorial pack --section SECTION_ID
  ```

  Omit `--section` for publication-only work, or use the context command's
  `--story`/`--assignment` selector to resolve the actual section. Doctrine and
  Humanus rule controls are complementary; load both. Retain the effective
  context hash and source revisions privately. A denied, missing, conflicting or
  ambiguous required context stops the pass; do not substitute seed YAML or
  escalate a failed user session to IAM. Explicit IAM operator access remains
  available when that is the selected authorized lane.
- Keep the returned doctrine, policy examples, model prompts and editorial
  reasons private. Do not copy them into public source, fixtures, issues, logs,
  feeds or reader content. Synthetic test guidance is safe for public tests.
- For explicitly offline file work, pass
  `--pack pack.json` (a Humanus policy pack; `papyrus editorial pack` exports
  the site's private effective pack). File mode is not current hosted policy.
- `TYPESAFE_API_KEY` for judgment policies (without it, rule policies still
  run and the result says the classifier lane is unavailable) and
  `OPENAI_API_KEY` for rewrite options.
- Know the article's desk (`--section`): desk policies replace publication
  controls with the same key. Doctrine still retains publication precedence and
  adds selected section guidance; surface conflicts instead of silently overriding it.

## The cycle

1. **Check** (read-only):

   ```bash
   papyrus editorial check --draft draft.md --section <desk> > check.json
   ```

   Each finding has `policyId`, `severity` (`error`/`warn`/`info`), `status`
   (`violation`, or `review` when the model is unsure), `message`, `excerpt`,
   `span` (UTF-16 offsets), and for judgment policies `probability`. `lanes`
   says whether each lane ran fully.

2. **Suggest** for the findings worth fixing, or for any passage:

   ```bash
   papyrus editorial suggest --draft draft.md --finding-id f-0123456789abcdef --note "shorter"
   papyrus editorial suggest --draft draft.md --select "Exact passage from the draft."
   ```

   A finding is rewritten as its whole sentence. Options never add facts;
   `factVerificationRequired: true` means an option changes a claim.

3. **Choose**: show the person the findings and options. Apply only the option
   they pick, replacing the target span in a working copy or in the article
   (save substantive revisions as a new Papyrus version). Do not resolve
   `review` findings on your own.

4. **Check again** after edits. Finding ids stay the same for unchanged
   sentences.

## Policies

- `papyrus editorial pack [--section <desk>]` prints the composed policy pack.
- `papyrus editorial import --profile publications/<pub>/style-profile.yml`
  turns a legacy style profile's lexicon, banned phrases and patterns, checks
  and guidance into publication policies (`--replace` overwrites same-key
  policies).
- New policies, the AI-writing tells starter pack, drafted judgment questions
  and recalibration from editors' decisions are in Administration → Editorial
  checks.

Never loosen a policy (disable it, raise a threshold) to make a draft pass;
report the conflict instead.
