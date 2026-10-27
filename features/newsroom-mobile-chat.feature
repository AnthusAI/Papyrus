Feature: Reach private chat from a phone newsroom
  Editors open chat from the existing mobile navigation, without a floating overlay.
  Messages remains available in the full navigation menu.
  The conversation remains usable when the keyboard reduces the viewport,
  and closing it returns them to their existing newsroom location.
  Resizing or scrolling the visual viewport while open keeps controls reachable.
  Crossing the mobile breakpoint preserves the draft and updates modal behavior;
  repeated close and reopen returns focus to the active conversation.

  Scenario: Open and close chat across phone sizes and orientation
    Given an authorized editor is viewing the newsroom on a phone
    When the editor opens chat from the visible mobile control
    Then the conversation and close control fit the viewport
    And keyboard focus stays within the mobile conversation
    And closing chat returns focus and preserves the newsroom location
    And browser Back closes mobile chat before leaving the newsroom
    And reloading open chat does not add another history entry
    And public or unavailable routes do not restore chat or add hidden history entries

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

  Scenario: Explain unavailable publishing access without suggesting an owner can grant it
    Given a signed-in editor has no eligible publishing Account
    When the editor opens private chat from mobile navigation
    Then the panel explains the setup blocker below its header
    And checking again refreshes access without granting it or sending a message

  Scenario: Compile the navigation icon dependency in publication consumers
    Given mobile navigation uses the existing icon package
    When the publication transpilation configuration is checked
    Then icon source exports are transpiled alongside the shared chat packages
