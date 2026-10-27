@brand-agnostic
Feature: A site's brand pack can be checked against the reference pack
  A site owns its publication/ brand pack: the npm package ships no publication
  code, so nothing upgrades the site's copy. `papyrus-app brand diff <id>` compares
  that copy with the reference pack in a Papyrus checkout. These scenarios are
  verified by scripts/test-brand-diff.mjs (npm run test:brand-diff).

  Scenario: A site whose pack matches the reference passes
    Given a site whose publication/ is the reference pack with package-style imports
    When I run papyrus-app brand diff for its brand id
    Then it reports that the pack matches and exits 0

  Scenario: A site with a stale pack is told what it is missing
    Given a site whose publication/ lacks the reference pack's logo component and font
    When I run papyrus-app brand diff for its brand id
    Then it lists the missing files and the differing brand.ts and exits 1

  Scenario: Site-only files are not drift
    Given a site pack with an extra file the reference does not have
    When I run papyrus-app brand diff for its brand id
    Then the extra file is listed as site-only and the command exits 0

  Scenario: An unknown brand id is an error
    Given no reference pack exists for the brand id
    When I run papyrus-app brand diff for it
    Then the command names the missing reference directory and exits 2
