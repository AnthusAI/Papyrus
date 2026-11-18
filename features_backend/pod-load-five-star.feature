@pod
Feature: A pod never grants five stars
  A rating in a note is one to four. A 5 is a five-star candidate: `pod check` reports it, and `pod load` refuses the rating and still loads the note, with
  no rating at all, and lists it as a candidate for a person to confirm in the newsroom. The Story gets no star rating from the load, and nothing that
  ranks, announces or features a Story by its stars sees one.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod file "best.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0051
      type: papyrus:Article
      title: The best one
      stage: copywriting
      rating: 5
      ---
      Words.
      """
    And the pod file "good.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0052
      type: papyrus:Article
      title: A good one
      stage: copywriting
      rating: 4
      ---
      Words.
      """
    And the pod is a git repository with everything committed

  Scenario: The check still reports a rating of 5
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'rating' is 5, which a pod never grants; this note is a five-star candidate, and a person confirms five stars in the newsroom. Use 4 here" for the note "best.md"

  Scenario: A rating of 5 is refused on load and the note is listed as a five-star candidate
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the pod report says "best.md: rating 5 refused, a pod never grants five stars; listed as a five-star candidate for a person to confirm in the newsroom"
    And the pod report says "five-star candidates: best.md"
    And the story for the note "best.md" carries the pod key "fiveStarCandidate" with the value "True"
    And the story for the note "best.md" carries no pod key "rating"

  Scenario: The candidate has no star rating and the load grants none
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "best.md" has no star rating in the newsroom
    And the story for the note "good.md" has no star rating in the newsroom

  Scenario: The newsroom shows the candidate as a proposal for a person
    Given the pod is loaded
    When I run "papyrus stories show" for the note "best.md"
    Then the load output says "Five-star candidate from the pod: a person confirms five stars in the newsroom"

  Scenario: A note with a rating of 4 is not a candidate
    When I load the pod with "papyrus pod load POD"
    Then the story for the note "good.md" carries the pod key "rating" with the value "4"
    And the story for the note "good.md" carries no pod key "fiveStarCandidate"

  Scenario: A rating that is not a number from one to five still stops the load
    Given the pod file "good.md" has "rating: 4" replaced by "rating: 9"
    And the pod's changes are committed
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 1
    And the pod report says "key 'rating' takes a whole number from 1 to 4"
    And the load did not sign in
    And the newsroom has no stories
