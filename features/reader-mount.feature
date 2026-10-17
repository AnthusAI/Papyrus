@brand-agnostic
Feature: Mounting the reader under a base path
  papyrus-app sync writes the reader route shims under the publication's
  readerBasePath so the publication owns "/". These scenarios are verified by
  scripts/test-sync-reader-base-path.mjs and scripts/test-staging-gated-path.ts
  (npm run test:sync-reader-base-path, npm run test:staging-gated-path), which
  run in test:ci:ts.

  Scenario: Sync with readerBasePath /information writes reader shims under app/information and none at the root
    Given a publication whose papyrus.config.ts sets readerBasePath "/information"
    When I run papyrus-app sync
    Then the home, edition date, article, archive and settings shims are under app/information
    And no reader shim exists at app/page.tsx, app/archive, app/articles, app/settings or app/[year]
    And the newsroom, api and preview shims stay at their own paths

  Scenario: A site-owned app/page.tsx is kept
    Given a publication with a site-owned app/page.tsx and readerBasePath "/information"
    When I run papyrus-app sync
    Then app/page.tsx is not overwritten

  Scenario: Sync without a base path is unchanged
    Given a publication with no readerBasePath
    When I run papyrus-app sync
    Then every shim is written at the same path as before

  Scenario: Staging gates only the reader when a base path is set
    Given readerBasePath "/information" and SITE_ENV staging
    Then "/information" and "/information/archive" are gated
    And "/", "/newsroom", "/api" and "/robots.txt" are public
