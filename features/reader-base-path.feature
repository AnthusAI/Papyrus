@brand-agnostic
Feature: Reader base path
  A publication can serve its Pretext reader under a public prefix such as
  /information. Every generated reader link, canonical redirect and cache
  revalidation carries the prefix. Sites without a prefix are unchanged.
  These scenarios are verified by the unit suite in scripts/test-reader-base-path.ts
  (npm run test:reader-base-path), which runs in test:ci:ts.

  Scenario: A brand with readerBasePath /information renders edition links under /information
    Given a reader base path of "/information"
    Then the edition path for "2026-10-07" is "/information/2026/october/07"

  Scenario: Article, section, page, archive and footer links carry the prefix
    Given a reader base path of "/information"
    Then every article, section, page, archive and footer path starts with "/information"

  Scenario: A non-canonical date URL redirects to the prefixed canonical path
    Given a reader base path of "/information"
    Then the route for "/information/2026/October/7" has the canonical path "/information/2026/october/07"

  Scenario: Revalidate refreshes prefixed paths
    Given a reader base path of "/information"
    Then revalidation targets the prefixed edition, article and archive paths

  Scenario: A brand without readerBasePath is unchanged
    Given no reader base path
    Then every reader path is identical to the unprefixed path
