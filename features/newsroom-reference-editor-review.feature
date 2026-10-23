@brand-agnostic @reference-editor-fixtures
Feature: An editor reviews references even when a prediction is unavailable
  Reference intake stays selectable while predictions are loading or absent.
  An authorized editor can approve or reject, explain optionally, and revise
  saved feedback without creating duplicate requests. These scenarios use only
  synthetic references in an isolated browser and never label production data.

  Scenario: Select a pending reference on desktop and mobile
    Given an isolated inbox of synthetic pending references
    When the editor selects a pending reference on desktop and mobile
    Then its detail offers approval and rejection and says no prediction was recorded
    And browser Back restores the previous reference and then clears the detail at the inbox
    And changing status filters preserves the selected reference and its unsaved explanation

  Scenario: Save and revise feedback with an optional explanation
    Given an isolated inbox of synthetic pending references
    When the editor approves without an explanation, adds feedback, and later rejects with a reason
    Then approval, rejection, and revised optional explanations survive a fresh page load
    And unchanged or just-saved feedback cannot create another completed write

  Scenario: Recover a failed review without duplicate clicks
    Given an isolated inbox of synthetic pending references
    When the editor double clicks approval and the save fails before a retry succeeds
    Then only one request is sent per attempt and the failed attempt retains the pending status and explanation

  Scenario: Restore the rejection reason from review history and clear an explanation
    Given an isolated inbox of synthetic pending references
    When the editor reloads a rejected reference and clears its saved explanation
    Then the reason from review history remains selected and the cleared explanation survives another reload
    And live feedback updates refresh an untouched form while preserving an unsaved draft

  Scenario: Distinguish publication and Section predictions without invented confidence
    Given an isolated inbox of synthetic pending references
    When the editor opens a reference with publication and Section predictions
    Then both prediction scopes are visible and missing confidence, version, and teaching counts are not invented
    And ordinary approval and agreeing with a prediction both keep the editor's chosen Section
    And revising accepted feedback retains the recorded Section until the editor explicitly removes it
    And a completed advanced review cannot be submitted again

  Scenario: Retry a failed prediction read without claiming no prediction exists
    Given an isolated inbox of synthetic pending references
    When the editor retries a failed prediction read
    Then the error is distinct from an absent prediction and approval stays available

  Scenario: Loading predictions does not block editorial review
    Given an isolated inbox of synthetic pending references
    When the editor opens a reference while predictions are loading
    Then loading is distinct from an absent prediction and approval stays available

  Scenario: A person without editing permission can inspect but cannot review
    Given an isolated inbox of synthetic pending references
    When a person without editing permission selects a reference
    Then its detail explains the permission requirement and neither review action can send a request

  Scenario: An empty inbox explains that no references have been imported
    Given an isolated inbox of synthetic pending references
    When the editor opens an inbox with no imported references
    Then the inbox explains the empty state without rendering reference rows
