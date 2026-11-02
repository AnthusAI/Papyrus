@brand-agnostic @needs-me-link-fixtures
Feature: On a phone the Needs me detail is its own full screen
  On a phone, opening a card in "What needs me" opens its detail in a sheet. The sheet used to rise from the bottom and stop at 85 percent
  of the screen, with the body capped at 70 percent, so the index showed behind and above the detail. The sheet now covers the whole
  screen: the header with the type's name sits at the top below the notch, the body fills the space between it and the bottom and
  scrolls when it is longer, and Previous and Next stay pinned at the bottom above the home bar. It has no border and no rounded top,
  because it is the screen. The detail sheets of the Assignments and Topics views get the same treatment; the Newsroom menu sheet
  stays a menu. These scenarios use synthetic data in an isolated browser at 390 by 844 pixels and never touch production.

  Scenario: The detail covers the whole viewport
    Given an isolated Needs me feed with four suggested links
    When the editor opens a card on a phone
    Then the sheet is exactly the viewport, with nothing of the index showing, the header at the top and Previous and Next at the bottom edge
    And the body fills the space between them rather than a fraction of it, and the sheet has no border and no rounded corners

  Scenario: A long detail scrolls inside the sheet while Previous and Next stay put
    Given an isolated Needs me feed with four suggested links
    When the editor opens a card on a screen only 560 pixels tall and scrolls the detail to its end
    Then the detail scrolls inside the sheet and the Previous and Next bar does not move from the bottom edge

  Scenario: Closing the sheet returns to the index
    Given an isolated Needs me feed with four suggested links
    When the editor opens a card on a phone and presses Escape
    Then the sheet is gone
