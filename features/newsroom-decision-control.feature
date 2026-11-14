@brand-agnostic
Feature: One Accept and Reject control, with an optional reason, everywhere a person decides
  A Reference and a generated idea are decided with the same control. Each mark has
  a word beside it, the reason is written in a textarea, and nothing opens as a
  dropdown or popover. The idea's decision is kept in the idea's front matter at
  generated.decision so the site Cyclotron can learn from it. These scenarios use
  synthetic fixtures in an isolated browser.

  Scenario: Accept and Reject show a mark and a word with a reason box
    Given an isolated page with a synthetic Reference and a synthetic generated idea
    When the editor looks at the control on each of them
    Then Accept and Reject each show an icon and a word
    And the reason is a textarea, not a dropdown or a popover

  Scenario: Rejecting an idea records the written reason
    Given an isolated page with a synthetic Reference and a synthetic generated idea
    When the editor types a reason on the idea and chooses Reject
    Then the decision, the reason, the editor and the time are recorded
    And the control says Recorded and that the reason was saved

  Scenario: The decision is kept in the idea's front matter
    Given an isolated page with a synthetic Reference and a synthetic generated idea
    When a decision is written to the idea's front matter
    Then it sits at generated.decision and the rest of the front matter is unchanged
    And a story started by a person never gets one

  Scenario: Accept moves the idea forward and Reject spikes it
    Given an isolated page with a synthetic Reference and a synthetic generated idea
    When the stage for each decision is chosen from the board's stage list
    Then Accept names the stage after Idea and Reject names Spiked with the reason passed along

  Scenario: A failed save is said in words
    Given an isolated page with a synthetic Reference and a synthetic generated idea
    When the idea's save fails
    Then the control shows the failure as text
