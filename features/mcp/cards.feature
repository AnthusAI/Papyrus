Feature: Optional MCP App cards
  A host that supports MCP Apps can present the same authorized tools as a conversation
  without giving the embedded view its credentials.

  Scenario: A reader explores a reference and a story
    Given a host with seeded reference and story results
    When it opens the reference card and navigates to a related story
    Then the card shows the records and their provenance as text
    And evidence and the next story step can be requested through the host

  Scenario: A staff member handles a stale reference decision
    Given a host with a seeded reference at revision 3
    When the staff member decides the reference after it has changed
    Then the card reports the stale state and refreshes the reference
    And the card never receives a bearer token

  Scenario: A client does not support apps
    Given a host that cannot display an app
    Then the tool retains its text and structured result

  Scenario: A staff member answers an open review from a Story
    Given a host with a Story and open reviews
    When the staff member answers a review that has changed
    Then the card refreshes the review before allowing another answer
    And publish gates and reviews without a revision have no answer controls
