@backend @reference-source-quality
Feature: A Reference carries one source quality rating from one to five
  Source quality says how good a Reference is as evidence: a landmark primary source is a five, an unreliable or content-free page is a one. It is a
  different thing from the stars an editor gives (reference-stars.feature), which say how interesting the editor finds the Reference. Stars live on the
  Reference itself. Source quality is a relation in the knowledge graph from the Reference to one of five shared concepts, "one-star quality" to
  "five-star quality", and the knowledge search reads it to rank what it finds.

  `papyrus references quality set` records a rating a person chose, and `papyrus references quality assess` asks a model for one. Both end in the same
  plan. A Reference has one current rating: a new rating supersedes the old relation and never deletes it, so the history of how a Reference was rated
  stays readable. Giving the same rating again writes nothing unless the rating is asked for afresh. Each rating records who gave it, when, and why.

  A model rates the Reference as source material. It is shown the publication's policies as background about what the publication cares about, and it
  is told not to mark a Reference down for disagreeing with them.

  Background:
    Given a Reference titled "Teens and AI companions" with no source quality rating yet

  Scenario: The first rating links the Reference to the concept for that many stars
    When the Reference is given a source quality of 4
    Then the plan writes one new quality relation scored 4 that points at the concept "quality.rating.4_star"
    And the plan supersedes 0 earlier quality relations

  Scenario: The concept for a rating is written the first time any Reference needs it
    Given the knowledge graph has no concept for 5 star quality yet
    When the Reference is given a source quality of 5
    Then the plan also writes the concept "Five-Star Quality"

  Scenario: A concept that exists is not written again
    When the Reference is given a source quality of 5
    Then the plan writes no concept

  Scenario: The same rating given again writes nothing
    Given the Reference already has a source quality of 3
    When the Reference is given a source quality of 3
    Then the quality plan writes no records at all
    And the plan names the relation that already holds the rating

  Scenario: A different rating supersedes the old one and keeps it
    Given the Reference already has a source quality of 2
    When the Reference is given a source quality of 4
    Then the plan writes one new quality relation scored 4 that points at the concept "quality.rating.4_star"
    And the plan supersedes 1 earlier quality relations
    And the superseded relation records that a rating of 4 replaced it

  Scenario: The same rating asked for afresh is recorded as a new rating
    Given the Reference already has a source quality of 3
    When the Reference is given a source quality of 3 afresh
    Then the plan writes one new quality relation scored 3 that points at the concept "quality.rating.3_star"
    And the plan supersedes 1 earlier quality relations

  Scenario: A rating records who gave it, when and why
    When "ryan" gives the Reference a source quality of 5 with the note "Primary survey data with a published method."
    Then the new quality relation records the rater "ryan", the note "Primary survey data with a published method." and the time of the rating

  Scenario Outline: A rating that is not a whole number from one to five is refused
    When the Reference is given a source quality of <rating>
    Then the quality rating is refused with "quality rating must be an integer from 1 to 5"

    Examples:
      | rating |
      | 0      |
      | 6      |
      | good   |

  Scenario: A model is told to rate the source and not its agreement with the publication
    Given the publication has the policy "Editorial stance" that says "We are sceptical of AI companion products."
    When the instructions for a model's quality assessment are written
    Then the instructions show the model the policy "We are sceptical of AI companion products."
    And the instructions say "Do not score the Reference by whether it complies with publication policies."
    And the instructions ask for a rating that is "an integer from 1 to 5"

  Scenario: A model's rating keeps its reasoning as the note, with at most three pieces of evidence and three caveats
    Given a model rated the Reference 4 because "A large, clearly described survey." with 5 pieces of evidence and 4 caveats
    When the model's assessment is turned into the note for the rating
    Then the note gives the reason "A large, clearly described survey."
    And the note lists 3 pieces of evidence and 3 caveats
