Feature: Adding a reference from the Newsroom makes a real Reference that an editor can accept and rate on the spot
  An editor pastes a web page address into the Add dialog on References. The address becomes a pending Reference that the list shows
  straight away, never a hidden training example. An editor who adds a page because it is good can accept it and give it one to five
  stars in the same dialog. Both are the editor's own decision, recorded through the same actions as the review buttons, from the
  Newsroom session. Everything is a button with a mark and words, so nothing depends on colour or on a drop-down.

  Scenario: A pasted address becomes a pending Reference
    Given an editor with the Add dialog open
    When the editor adds an address and makes no decision
    Then the address is registered as a pending Reference
    And nothing is accepted and nothing is rated
    And the dialog says the reference was added and is pending review

  Scenario: Accepting and rating while adding
    Given an editor with the Add dialog open
    When the editor adds an address, accepts it and gives it 5 stars
    Then the address is registered first
    And the same Reference is then accepted with the editor's sentence
    And the same Reference is then rated 5 of 5 stars
    And the dialog says it was added, accepted and rated

  Scenario: A rating is also an acceptance, and the stars fill to the left
    Given an editor with the Add dialog open
    When the editor adds an address and gives it 3 stars without accepting
    Then the dialog turns Accept on, fills the first three stars and sends no separate accept, because the newsroom accepts a rated pending Reference itself

  Scenario: An address that is already a Reference
    Given an editor with the Add dialog open
    When the editor adds an address that is already an accepted Reference
    Then the dialog says the address was already a Reference
    And it is not accepted a second time

  Scenario: The decision fails after the Reference exists
    Given an editor with the Add dialog open
    When the editor accepts and rates while adding, and both of those saves fail
    Then the Reference still exists
    And the dialog says which step did not save and why

  Scenario: A refused address says so and keeps what was typed
    Given an editor with the Add dialog open
    When the newsroom refuses the address
    Then the dialog says the reference was not added
    And the address stays in the box

  Scenario: Only a secure web address and a whole rating of 1 to 5 are accepted
    Given an editor with the Add dialog open
    When the editor adds an address that is not https, or a rating outside 1 to 5
    Then nothing is sent to the newsroom

  Scenario: The controls are buttons with marks and words
    Given an editor with the Add dialog open
    Then accepting is a button that reads Accept or Accepted with a check mark
    And the rating is five star buttons with a written summary such as "4 of 5 stars" or "Not rated"
    And pressing the chosen star again clears the rating
    And the dialog has no drop-down and no outlines
