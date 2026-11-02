@auto-accepted-list
Feature: An editor can review everything that was accepted automatically, and reject what they disagree with
  The Cyclotron accepts a confident Reference nobody voted on, and a monitor with a fixed delivery rule accepts what matches its rule. Both
  leave the Reference accepted, marked "Accepted automatically", with the reason. The References page has a filter of that name, opened by
  the address ?status=auto-accepted. It lists every such Reference, newest acceptance first, as the same cards the feed uses, with the same
  Accept and Reject buttons and a written reason box. Accept confirms the automatic acceptance as the editor's own vote, with an optional
  explanation; Reject overturns it and needs one. Either replaces the automatic actor with the editor, so the Reference leaves the list, counts
  as a human vote for the threshold, and is sent to the Cyclotron with the explanation as its comment (features_backend). It reads the database a page at a time from the accepted References, with
  the filter applied by the database, so it works with several thousand References and needs no index of its own. An editor's own
  acceptance is never in it, and a Reference leaves it once an editor has voted.

  Scenario: The address opens the list, newest first, with the reason and the confidence
    Given a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance
    When the editor opens the References page at the address ?status=auto-accepted
    Then the Accepted automatically filter is selected and shows no count
    And only the automatic acceptances are listed, newest first, each with who accepted it, how sure the Cyclotron was, and the reason it recorded
    And the editor's own acceptance is not listed
    And the cards carry the same Accept and Reject buttons, with no dropdown

  Scenario: Choosing the filter writes the address, and more are read a page at a time
    Given a newsroom with more automatic acceptances than one page holds
    When the editor chooses the Accepted automatically filter and reaches the end of the list
    Then the address says ?status=auto-accepted
    And the next page is read from where the last stopped, and no card appears twice

  Scenario: Rejecting asks for a reason and takes the card out of the list
    Given a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance
    When the editor taps Reject on an automatically accepted card
    Then the reason box is empty and a reason is required before anything is sent
    And once the editor writes a reason and records it, the Reject is sent with that reason and the card leaves the list

  Scenario: Confirming an automatic acceptance with an explanation records the editor's vote and takes the card out
    Given a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance
    When the editor taps Accept on an automatically accepted card and writes an explanation
    Then the reason box is offered, empty, and no reason is required
    And nothing is sent until the editor records it, and then the Accept is sent with that explanation and the card leaves the list

  Scenario: Confirming without an explanation is allowed, and an explanation typed first goes out with the tap
    Given a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance
    When the editor taps Accept on an automatically accepted card and records it without a word
    Then the Accept is sent with no explanation, rather than an empty one, and the card leaves the list
    And an explanation typed before tapping Accept is sent with the tap

  Scenario: The detail pane confirms the same way as the card
    Given a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance
    When the editor opens an automatically accepted reference and taps Accept
    Then the box is offered first and nothing is sent until Record

  Scenario: An empty list says so in plain words
    Given a newsroom where nothing has been accepted automatically
    When the editor opens the References page at the address ?status=auto-accepted
    Then it says that nothing has been accepted automatically yet

  Scenario: On a phone nothing scrolls sideways
    Given a newsroom with Cyclotron acceptances, a rule acceptance and an editor's own acceptance
    When the editor opens the list on a phone
    Then nothing scrolls sideways, the tap targets are large and the icons are Lucide

  Scenario: Only the newest end of the accepted References is read, whatever their number
    Given 5000 accepted References, 250 of them accepted automatically
    When the first page of the list is read
    Then the page holds the newest automatic acceptances and only a small part of the 5000 is read
    And the next page continues where it stopped, a database page with no match is not taken for the end, and no acceptance is listed twice

  Scenario: Both kinds of automatic acceptance are named in the database filter, and only they
    Given the list's database filter
    Then it names auto:cyclotron and auto:rule, current versions only
    And an editor's acceptance is refused even if a read returns it
