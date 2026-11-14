Feature: A Story keeps the date it was first published, and the served version says when it went live
  Readers and every list on the site order Stories by when they first appeared, so a corrected article does not pretend to be new. A Story has two
  public times. "Published" is the moment the Story was first published: the first publish sets it, every later version carries it, and nothing that
  happens afterwards (a new version, a takedown, a republish, a rating) changes it. "Version published" is the moment the version now served went live,
  and who published it: only publishing a new version moves it. Publishing also leaves the version's own record alone: who saved it, when, and the
  editor's "what changed" text stay on the version, because that text is the start of the Story's revision history. `papyrus stories backfill-published-dates`
  moves Stories published before this change to the new meaning, using only what their versions recorded, and lists the Stories it cannot decide for a person.

  Background:
    Given a Story first published on 4 November 2026 at 15:02 by Pat

  Scenario: Publishing a new version keeps the first publication time
    Given an editor saves a new version on 11 November 2026 with the reason "tighten the opening"
    When the editor Sam publishes that version on 11 November 2026 at 09:40
    Then the Story's published time is still 4 November 2026 at 15:02
    And the served version's published time is 11 November 2026 at 09:40 by Sam
    And the published row says the same two times

  Scenario: Publishing keeps the version's own record
    Given an editor saves a new version on 11 November 2026 with the reason "tighten the opening"
    When the editor Sam publishes that version on 11 November 2026 at 09:40
    Then the version still says it was saved on 11 November 2026 by the saving editor, with the reason "tighten the opening"

  Scenario: A Story published again after a takedown keeps its first date
    When the Story is taken down on 6 November 2026
    And an editor saves a new version on 7 November 2026 with the reason "fix the claim"
    And the editor Sam publishes that version on 8 November 2026 at 10:00
    Then the Story's published time is still 4 November 2026 at 15:02
    And the served version's published time is 8 November 2026 at 10:00 by Sam

  Scenario: Taking a Story down leaves the version's own record alone
    When the Story is taken down on 6 November 2026
    Then the version still says it was saved on 4 November 2026 by the saving editor, with the reason "created"

  Scenario: A new draft has not gone live
    When an editor saves a new version on 11 November 2026 with the reason "tighten the opening"
    Then the new draft carries the first publication time and has no version published time

  Scenario: A rating does not change any public date
    When an editor gives the Story four stars
    Then the Story's published time is still 4 November 2026 at 15:02
    And the served version's published time is 4 November 2026 at 15:02 by Pat

  Scenario: Publishing unchanged content again does nothing
    When the editor Sam publishes the Story again on 12 November 2026 at 08:00
    Then no row of the Story was written
    And the served version's published time is 4 November 2026 at 15:02 by Pat
