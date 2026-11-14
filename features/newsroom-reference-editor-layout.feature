@brand-agnostic @reference-editor-layout
Feature: Reference review remains reachable on a laptop screen
  Secondary import controls and prediction activity must not consume the
  available space for references, even when those controls are expanded.
  This full-app check runs only when an
  explicit local demo URL is supplied; it never opens a production newsroom.

  Scenario: Select a pending reference at 1280 by 720
    Given an explicitly configured local reference demo
    When the editor opens the full newsroom at 1280 by 720
    Then a reference row is visible inside the list viewport and pending feedback is reachable

  Scenario: The feed, the detail pane and the rating grid fill the viewport compactly
    Given an explicitly configured local reference demo
    When the editor opens the References page at four desktop sizes
    Then the feed scroller and the Detail pane both end at the bottom of the viewport
    And the confidence bar sits above the buttons on a card and in the Detail pane
    And the space under a card's You buttons is no larger than the card's side padding
