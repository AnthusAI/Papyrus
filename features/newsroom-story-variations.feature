@story-variations
Feature: An editor sees the variations of an idea side by side and accepts or rejects them
  When an idea run files an idea it also offers variations: different ways to connect the same item to what the newsroom knows (another Reference, another
  Story, a concept). Wherever an idea is reviewed (the Story detail, the Stories board's card detail, the idea batch in Needs me) the variations sit side by side,
  each leading with its point and then its headline, deck and what it connects to, as links to the Reference, the Story or the concept. An editor accepts a
  variation, which saves that wording as the Story's next version with `variationId` recording where it came from, or rejects it with an optional reason. A
  Story has one accepted wording at a time: accepting a second variation makes another version and puts the first back on offer, its wording staying in the
  version history. A wording that could not be saved is not recorded as accepted. Accept and Reject are words with Lucide icons, never colour alone; there
  are no dropdowns and no outlines; on a phone the cards stack in one column. With one way to connect there is one card and it says so; with none, nothing shows.

  Scenario: Three variations sit side by side, each leading with its point and linking to what it connects to
    Given a Story with three variations
    When the editor opens the variations
    Then the three cards share a row in the order they were offered with the point first and connections that link to a Reference, a Story and a concept

  Scenario: Accepting a variation makes its wording the Story's next version and records the decision
    Given a Story with three variations
    When the editor accepts the second variation and writes why
    Then the wording is saved as the next version first, and the variation is recorded as accepted by the editor with the reason

  Scenario: Accepting a second variation puts the first back on offer
    Given a Story with three variations
    When the editor accepts the first variation and then the third
    Then two versions were saved, the third variation is accepted and the first is on offer again and can be accepted again

  Scenario: Rejecting a variation keeps the reason and changes nothing on the Story
    Given a Story with three variations
    When the editor rejects the third variation and writes why
    Then no version was saved and the reason stays readable on the card

  Scenario: A wording that could not be saved is not an accept
    Given a Story with three variations whose next version cannot be saved
    When the editor accepts the first variation
    Then the card shows the error and nothing is recorded as accepted

  Scenario: With one way to connect there is one card, and with none nothing shows
    Given a Story with one variation
    When the editor opens the variations
    Then the single card says only one way to connect this was found and a Story with no variations shows nothing

  Scenario: On a phone the cards stack and the buttons are big enough to tap
    Given a Story with three variations
    When the editor opens the variations on a phone
    Then the cards are in one column, nothing scrolls sideways and Accept and Reject are at least forty-four pixels tall

  Scenario: Accept and Reject are words with icons, with no dropdowns and no outlines
    Given a Story with three variations
    When the editor rejects the first variation
    Then Accept and Reject are words with Lucide icons, the state is a word with an icon, and there are no dropdowns, borders or outlines
