@brand-agnostic @notification-center-fixtures
Feature: The Notification Center answers "What needs me?" with a feed of cards
  The console home is a feed in the style of the References feed: flat tones and rounded cards, no borders or lines. A short
  header says what waits ("3 drafts and 12 references waiting for you") and Drafts, References and Other pills narrow it. Each AI
  draft is its own card with its headline, dek, section, cited sources, evidence line and the cited source's picture, then Accept or
  Reject with an optional Why. A review request that covers several drafts is not shown as a batch: it is a small caption on each
  card ("from Monitor stories run, Oct 27") and the request closes itself once its last draft is decided. References needing review
  are the References feed's own cards. Flags are slim cards with Acknowledge. When nothing waits the page says "All caught up" and
  lists what was decided last. These scenarios use synthetic drafts and references in an isolated browser, at 375 and 1440 pixels,
  and never touch production.

  Scenario: Each draft is its own card, shown so it can be judged in place
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens the Notification Center at 375 and 1440 pixels
    Then every draft shows its headline, dek, section, evidence line, source chips, batch caption and a link to its full draft in Proposals
    And every draft has large Accept and Reject buttons and a full-width Why box, with no prediction row, no borders and nothing scrolling sideways
    And the header counts drafts, the cards are one column on a phone and three on a wide screen, and the retired Approve, Steer and Agree wording is gone

  Scenario: Accept approves the Proposal, Reject declines it, and the request closes itself
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor accepts one draft, rejects one with one tap and the "Not this kind of story" chip and a Why, and accepts the last
    Then each Proposal is moved to approved or declined, decided cards stay in place showing their answer, and the request stays open until the last draft is decided
    And the request closes with every decision recorded, "not this kind" as its one steering signal, and the page says "All caught up" and lists what was decided

  Scenario: Accepting every draft or rejecting every draft is one plain answer
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor accepts all three drafts, and in another batch rejects all three
    Then the answers are an approval and a rejection, and a plain rejection carries no steering signal

  Scenario: A refused move and a held draft are said in words
    Given an isolated Notification Center with a batch of three AI drafts
    When a Proposal refuses the move, or a draft is on hold in Proposals
    Then the draft stays undecided, says why in words, keeps its buttons, and nothing is recorded

  Scenario: Drafts decided in Proposals, or not in Proposals at all, never strand a request
    Given an isolated Notification Center with a batch of three AI drafts
    When the drafts were already decided in Proposals, or none or only some of them can be opened here
    Then the request closes itself, takes Accept or Reject on the request, or lets the openable drafts finish it
    And a failed load offers Try again

  Scenario: References are the feed's own cards and the pills narrow the page
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor looks at pending References and uses the Drafts and References pills at 375 and 1440 pixels
    Then each Reference card shows the Cyclotron's Accept or Reject with its confidence, or says there is no prediction
    And the card opens the References queue, a rating is saved through the References review, and an empty pill says so

  Scenario: Drafts is reachable under Editorial work
    Given the organizer navigation
    When the editor looks at Editorial work
    Then Drafts opens the Proposals panel
