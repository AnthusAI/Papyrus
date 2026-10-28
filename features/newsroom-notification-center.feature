@brand-agnostic @notification-center-fixtures
Feature: The Notification Center answers "What needs me?" with one feed that mixes everything that may need a person
  The console home is a single feed in the style of the References feed: flat tones and rounded cards, no borders or lines. It mixes
  References, AI drafts, story reviews, held email, captures that may be cut off, and flags. Hard gates come first. After them the
  order is the value of the editor's input: how unsure the Cyclotron is, times how much the item matters, times how fresh it is, with
  no more than two items of one type in a row while another type waits. The order is taken once when the editor arrives and then left
  alone. Pills narrow the feed to one type and count what waits. Items the Cyclotron is confident about do not ask for the editor;
  they wait under "Decided automatically", where they can be overruled. Every card has the References feed's Accept and Reject grid,
  and a card opens the same detail pane whatever its type, with a body that fits it. Ignoring an item decides nothing: each card says
  what happens if it is left alone. A slim strip says how much the editor has shaped the feed this week. These scenarios use synthetic
  data in an isolated browser, at 375 and 1440 pixels, and never touch production.

  Scenario: Each draft is its own card, and its detail pane carries the whole draft
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens the Notification Center at 375 and 1440 pixels
    Then every draft card shows its type, headline, dek and what happens if it is left alone, with Accept and Reject and no prediction row
    And the header counts drafts, nothing scrolls sideways, no card has a border, and the retired Approve, Steer and Agree wording is gone
    And opening a draft shows its headline, section, evidence, citations, a link to the full draft in Proposals and a Why box

  Scenario: Accept approves the Proposal, Reject declines it, and the request closes itself
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor accepts one draft, rejects one with a Why and the "Not this kind of story" chip written in the detail pane, and accepts the last
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

  Scenario: References keep the Cyclotron row and the pills narrow the feed
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor looks at pending References and uses the Drafts and References pills at 375 and 1440 pixels
    Then each Reference card shows the Cyclotron's Accept or Reject with its confidence, or says there is no prediction
    And a card opens the same detail pane the References page has, a rating is saved through the References review, and an empty pill says so

  Scenario: Hard gates come first, types are mixed, and the pills count and filter
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens a feed that mixes a hard gate, drafts, References and a held email at 375 and 1440 pixels
    Then the hard gate is the first card and says it is a hard gate, and no third card of one type follows two of the same while another type waits
    And the pills count what waits for each type and a pill narrows the feed to that one type

  Scenario: Confident items wait under Decided automatically and can be overruled
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor has confirmed ten of the Cyclotron's predictions and a Reference arrives that it is very sure about
    Then that Reference is not in the feed, it is listed under Decided automatically with an Overrule button, and the "You're shaping this" strip counts the week's decisions and agreements

  Scenario: The same detail pane opens for every type
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens a hard gate, a draft, a held email and a Reference
    Then each opens in the one detail pane with a body that fits its type, a held email's text is inert and its links are not clickable, and a Reference shows our captured record

  Scenario: Ignoring an item leaves the default
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens and reads items without deciding them
    Then nothing is moved, answered, rated or decided, and each card says what happens if it is left alone

  Scenario: A held email is decided with the same Accept and Reject
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor rejects a held email with a Why written in its detail pane
    Then the email is rejected with that reason, its card shows the answer, and nothing else is changed

  Scenario: A draft's label and explanation come in either order, and the explanation can be changed later
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor accepts a draft and then writes its Why, writes a Why and then rejects another, closes the request, and changes a Why afterwards
    Then the Why box stays open and editable after the vote, a Why written after the vote is saved onto it with a Saved tick, and a Why written first goes with the vote
    And a reopened draft and its card show the saved reason, and changing a Why after the request closed rewrites the answer's words without touching the choices or moving a Proposal

  Scenario: A reason that cannot be saved is said in words and never lost
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor writes a Why after the vote and the save is refused
    Then the page says in words that the note could not be saved and is kept, the typed text stays in the box, and tapping away saves it

  Scenario: A stage review, a hard gate and a flag take their note in either order
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor answers a hard gate and then writes its note, and writes a flag's note before acknowledging it and changes it afterwards
    Then each note is saved onto the existing answer, the choice and the person who answered stay as they were, and the card shows the note

  Scenario: A held email and a Reference take their reason in either order
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor rejects a held email and then writes its reason, and accepts a Reference and then writes its reason
    Then the held email's decision is sent again with the reason so the recorded reason changes, the Reference's rating is saved again with its note, and each reopens showing its reason

  Scenario: Previous and Next stay in the bottom-right corner of the screen
    Given an isolated Notification Center with a batch of three AI drafts
    When the editor opens a draft at 1440 by 900, 1440 by 1300 and 1024 by 768 and scrolls the page and the feed, and again on a phone
    Then the Previous and Next bar's bottom-right corner is the viewport's bottom-right corner, other sections below the feed never push it up, and on a phone it is the fixed bottom of the sheet

  Scenario: Drafts is reachable under Editorial work
    Given the organizer navigation
    When the editor looks at Editorial work
    Then Drafts opens the Proposals panel
