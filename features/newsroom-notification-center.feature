@brand-agnostic @notification-center-fixtures
Feature: The Notification Center shows each AI draft and decides it with Accept or Reject
  A review request about AI drafts (a trend story batch, a monitor story batch, an idea batch) shows every
  draft in place: its headline, dek, section, evidence, cited sources with links, and the way to open the full
  draft in Proposals. The editor answers each draft with Accept or Reject and an optional Why. Accept approves the
  Proposal, Reject declines it, and once every draft is decided the request closes itself with each decision
  recorded. Nothing here is published, and a deadline only closes the request. These scenarios use synthetic
  drafts and references in an isolated browser, at 375 and 1440 pixels, and never touch production.

  Scenario: Each draft is shown so it can be judged in place
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens the Notification Center at 375 and 1440 pixels
    Then every draft shows its headline, dek, section, evidence line, linked sources and a link to its full draft in Proposals
    And every draft has large Accept and Reject buttons and a full-width Why box, and nothing scrolls sideways
    And the header counts AI drafts to review and the retired Approve, Steer and Agree wording is gone

  Scenario: Accept approves the Proposal, Reject declines it, and the request closes itself
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor accepts one draft, rejects one as not this kind of story with a Why, and accepts the last
    Then each Proposal is moved to approved or declined and the request stays open until the last draft is decided
    And the request closes with every decision recorded and "not this kind" as its one steering signal

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
    And a failed load offers Try again, and a request with no deadline says so plainly

  Scenario: Needs attention shows the Cyclotron's suggestion and opens the review queue
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor looks at pending references in Needs attention at 375 and 1440 pixels
    Then each shows the Cyclotron's Accept or Reject with its confidence, or says there is no prediction
    And the row opens the reference review queue and the suggestion itself is read only

  Scenario: Drafts is reachable under Editorial work
    Given the organizer navigation
    When the editor looks at Editorial work
    Then Drafts opens the Proposals panel
