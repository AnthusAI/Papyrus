@brand-agnostic @reference-editor-fixtures
Feature: An editor reviews references even when a prediction is unavailable
  Reference intake stays selectable while predictions are loading or absent.
  An authorized editor can approve or reject, explain optionally, and revise
  saved feedback without creating duplicate requests. These scenarios use only
  synthetic references in an isolated browser and never label production data.

  Scenario: Select a pending reference on desktop and mobile
    Given an isolated inbox of synthetic pending references
    When the editor selects a pending reference on desktop and mobile
    Then its review card has a Cyclotron row that says there is no prediction and a You row with Accept and Reject
    And browser Back restores the previous reference and then clears the detail at the inbox
    And changing status filters preserves the selected reference and its unsaved explanation

  Scenario: Save and revise feedback with an optional explanation
    Given an isolated inbox of synthetic pending references
    When the editor accepts, adds a Why note, and later rejects by choosing a reason chip
    Then the answers, the reason and the Why note survive a fresh page load
    And tapping the selected answer again never unselects it or sends another write

  Scenario: Recover a failed review without duplicate clicks
    Given an isolated inbox of synthetic pending references
    When the editor double taps Accept and the save fails before a retry succeeds
    Then only one request is sent per attempt and the failed attempt says so in words and keeps the Why note

  Scenario: Restore the rejection reason from review history and clear an explanation
    Given an isolated inbox of synthetic pending references
    When the editor reloads a rejected reference and clears its saved explanation
    Then the reason from review history remains selected and the cleared explanation survives another reload
    And live feedback updates refresh an untouched card while preserving an unsaved draft

  Scenario: Distinguish publication and Section predictions without invented confidence
    Given an isolated inbox of synthetic pending references
    When the editor opens a reference with publication and Section predictions
    Then the Cyclotron row highlights its Accept or Reject with its confidence and never invents one
    And accepting by tap or by the A key keeps the editor's chosen Section
    And the Cyclotron's matching or differing answer is marked with a check or cross as well as colour
    And the human answer is final and replaces the Cyclotron's

  Scenario: Retry a failed prediction read without claiming no prediction exists
    Given an isolated inbox of synthetic pending references
    When the editor retries a failed prediction read
    Then the error is distinct from an absent prediction

  Scenario: Loading predictions does not block editorial review
    Given an isolated inbox of synthetic pending references
    When the editor opens a reference while predictions are loading
    Then the Cyclotron row says Loading and the controls stay usable

  Scenario: A person without editing permission can inspect but cannot review
    Given an isolated inbox of synthetic pending references
    When a person without editing permission selects a reference
    Then the card says in words that editor access is required and no tap sends a request

  Scenario: Work through the queue on a phone and on a desktop
    Given an isolated inbox of synthetic pending references
    When the editor works through the pending queue at 375 and 1440 pixels
    Then a bottom bar shows Previous, the position and Next with one URL per item
    And swiping left or right and the arrow keys move through the queue
    And after the last item the page says All caught up

  Scenario: The review card is the same on a phone and a desktop
    Given an isolated inbox of synthetic pending references
    When the editor opens a reference at 375 and 1440 pixels
    Then the Cyclotron row sits above the You row and the Why box spans the card
    And every icon is a Lucide icon and nothing scrolls sideways

  Scenario: An empty inbox explains that no references have been imported
    Given an isolated inbox of synthetic pending references
    When the editor opens an inbox with no imported references
    Then the inbox explains the empty state without rendering reference rows
