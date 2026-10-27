Feature: Reach private chat from a phone newsroom
  Editors can open chat without discovering a clipped desktop toolbar.
  The conversation remains usable when the keyboard reduces the viewport,
  and closing it returns them to their existing newsroom location.

  Scenario: Open and close chat across phone sizes and orientation
    Given an authorized editor is viewing the newsroom on a phone
    When the editor opens chat from the visible mobile control
    Then the conversation and close control fit the viewport
    And keyboard focus stays within the mobile conversation
    And closing chat returns focus and preserves the newsroom location

  Scenario: Use chat with a reduced keyboard viewport
    Given an authorized editor is viewing the newsroom on a phone
    When the keyboard reduces the available conversation height
    Then the message composer and close control remain reachable
    And the transcript scrolls without horizontal page overflow

  Scenario: Preserve desktop controls and access boundaries
    Given the newsroom changes between mobile and desktop widths
    When the chat shell updates its responsive controls
    Then desktop layout keeps its existing toolbar behavior
    And an unauthorized visitor has no chat entry point
