@brand-agnostic
Feature: Reader video loading
  Reader pages carry many videos. A page load must not download video bytes for
  videos the reader has not scrolled to, must not fetch a video's file more than
  once, and must not swap to a different themed file after hydration.
  These scenarios are verified by the unit suite in scripts/test-video-loading.ts
  (npm run test:video-loading), which runs in test:ci:ts.

  Scenario: The server render attaches no video source
    Given a video that has not hydrated
    Then the loading plan attaches no source and preloads nothing

  Scenario: A video far from the viewport attaches no source
    Given a hydrated video that is not near the viewport
    Then the loading plan attaches no source and preloads nothing

  Scenario: A video near the viewport with a poster preloads nothing
    Given a hydrated video near the viewport that has a poster
    Then the loading plan attaches the source and preloads nothing

  Scenario: A video near the viewport without a poster preloads metadata only
    Given a hydrated video near the viewport that has no poster
    Then the loading plan attaches the source and preloads metadata

  Scenario: The video element is not remounted when hydration completes
    Given a video that hydrates and then resolves its theme
    Then the element key depends on the resolved source only after the source is attached
