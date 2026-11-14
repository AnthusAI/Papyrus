Feature: Review cards say what actually happened
  The Notification Center shows each review request as a card. A flag is informational, so an editor
  acknowledges it: nothing is approved, and the card says "Acknowledged by", never "Accepted by". Soft reviews
  and hard gates keep accept and reject. Answers stored before this change recorded a flag acknowledgement as
  "approve"; those still read as Acknowledged. A card about a story that has since been deleted keeps the id but
  says "(story deleted)", so nobody follows a link to nothing.

  Scenario: Acknowledging a flag is stored as an acknowledgement and shown as one
    Given a site with no review requests
    When the procedure "reference-intake" raises a flag on story "story-1" saying "Two sources disagree"
    And the editor acknowledges the request
    Then the stored decision is "acknowledge"
    And the outcome is "approved"
    And the card says "Acknowledged by editor" and not "Accepted by"

  Scenario: A flag answered before this change as "approve" still reads as acknowledged
    Given a flag answered with the old decision "approve" by "Ed Itor"
    Then the card says "Acknowledged by Ed Itor" and not "Accepted by"

  Scenario: A hard gate keeps accept semantics
    Given a hard gate answered with the decision "approve" by "Ed Itor"
    Then the card says "Accepted by Ed Itor" and not "Acknowledged by"

  Scenario: Only a flag can be acknowledged
    Given a site with no review requests
    When the procedure "ruling" raises a hard gate on story "story-1" saying "Approve this ruling summary"
    Then acknowledging the request is refused because only a flag is acknowledged

  Scenario: Steering and automation read an acknowledgement exactly as they read the old flag approval
    Given a site with no review requests
    When the procedure "reference-intake" raises a flag on story "story-1" saying "Two sources disagree"
    And the editor acknowledges the request
    Then "reference-intake" has no unapplied steering

  Scenario: A card about a deleted story says so
    Given an open flag about the story "story-gone" that no longer exists
    Then the card says "About: story story-gone (story deleted)"

  Scenario: A card about a story that still exists shows its title
    Given an open flag about the story "story-1" titled "Board refuses registration" that still exists
    Then the card says "About: Board refuses registration" and not "(story deleted)"
