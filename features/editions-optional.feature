@brand-agnostic
Feature: Editions are an optional publication setting
  A publication chooses whether it is organized into dated editions. The
  setting is off unless a brand turns it on. With editions off the
  publication is a plain stream of items: the home page is the newest items,
  each item lives at a flat article address, and sections are filters. With
  editions on, the dated edition routes, archive and masthead date behave as
  before.

  Scenario: Editions are off unless a brand turns them on
    Given a brand without an editions setting
    Then editions are disabled
    And a brand with editions enabled has editions enabled
    And a brand with editions explicitly disabled has editions disabled

  Scenario: With editions off the home page is the newest published articles first
    Given published articles "newer-story" and "older-story", newest first
    When the item stream is built for the home page
    Then the first stream item is "newer-story"
    And the stream has no edition date in it

  Scenario: Sections are filters on the stream
    Given published articles "newer-story" and "older-story", newest first
    When the item stream is built for the section "Security"
    Then every stream item is in the section "Security"
    And the stream still offers the sections "Security" and "Culture"

  Scenario: An unknown section filter shows the whole stream
    Given published articles "newer-story" and "older-story", newest first
    When the item stream is built for the section "No Such Section"
    Then the stream shows every item

  Scenario: With editions off a published article is listed although no edition exists
    Given a published article "standalone-story" and no editions at all
    When the item stream is built for the home page
    Then the first stream item is "standalone-story"

  Scenario: With editions off the home page reads articles from the item index, not from editions
    Then the home page loads its stream from the newest published articles and never lists editions

  Scenario: With editions off an empty publication says nothing is published yet
    Given no published articles
    When the item stream is built for the home page
    Then the stream is empty
    And the item stream view says "Nothing published yet"

  Scenario: With editions off the edition routes and archive are not found
    Given a brand without an editions setting
    Then the edition date, edition item, edition page, edition section, archive and archive API routes all answer not found when editions are off

  Scenario: With editions off no edition routes are enumerated at build time
    Given a brand without an editions setting
    Then no edition date routes are enumerated for the build

  Scenario: With editions on the dated edition routes are served
    Given a brand with editions enabled
    Then the edition path for "2026-10-07" is "/2026/october/07"
