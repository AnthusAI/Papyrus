Feature: Editors rate a Reference with stars and the idea pipeline reads the rating
  An editor who curates References can give any of them one to five stars while they accept or reject. The stars say how interesting the editor finds the
  Reference. They are not a vote and not relevance: they never change whether a Reference is accepted, rejected or pending, and they are never sent to the
  Cyclotron as a label. The newest rating wins and records who gave it and when, on the Reference itself, beside its latest vote; clearing a rating removes
  who and when too.
  The idea pipeline reads the rating because a signal nobody reads is worth nothing. Stars are among the strongest human signals, with the Messages editors
  write on a Reference and the reason they gave when they accepted it, and the three combine. One ordering decides everything: each signal that is for a
  Reference counts once (good stars, a message, an accept reason), low stars take one away, and a tie goes to more stars. So an accepted Reference with five
  stars and a message from an editor is written first, ahead of anything without both, and a Reference with one or two stars is written after the rest, never
  excluded. Stars alone, with no other evidence, are enough to enter the queue because an editor decided. A pack that holds a highly rated Reference is offered
  earlier, and when a pack has to be trimmed the Reference editors care about most is kept longest.
  The writer is told how many stars the editors gave as direction about what to look for, in the same way as the accept reason: it has no handle, grounds no
  sentence, and is never reported. A rating on its own does not satisfy the standard that an idea is more than a summary of its source. A changed rating is
  something new the newsroom knows, so an idea that was rejected is written again. A pending Reference is never a single-item idea, but its stars are kept as
  context. When a highly rated Reference still yields no idea, the run record says so and why, and the curation flag names it.

  Scenario: A rating is recorded beside the vote and the newest rating wins
    Given an editor rated a Reference 4 stars
    When the editor rates it 2 stars
    Then the Reference records 2 stars with who rated and when
    And the Reference's vote and curation status are exactly as they were

  Scenario: Clearing a rating removes who and when
    Given an editor rated a Reference 4 stars
    When the editor clears the rating
    Then the Reference records no stars, no rater and no time

  Scenario: A rating outside one to five is refused
    When an editor rates a Reference 6 stars
    Then the rating is refused with the range one to five

  Scenario: Stars are never a Cyclotron label
    Given a pending Reference rated 5 stars
    Then the Reference has no vote for the Cyclotron to learn from
    And a vote carries no stars

  Scenario: An accepted Reference with five stars and an editor's message is written first
    Given the site has a Reference with a lively thread and a Reference with five stars and a message and a Reference the Cyclotron scores very high
    When the idea queue is ordered
    Then the Reference with five stars and a message is first

  Scenario: Good stars alone put a Reference in the queue
    Given a Reference rated 5 stars with no other evidence
    When the idea queue is ordered
    Then the Reference is in the queue

  Scenario: One or two stars put a Reference last without excluding it
    Given a site whose best-scored Reference an editor rated 1 star
    When the idea queue is ordered
    Then that Reference is last in the queue
    And every Reference is still in the queue

  Scenario: A pack with a five star member is offered first and keeps that member when trimmed
    Given a pack whose last member an editor rated 5 stars
    When the packs are ranked and the pack is trimmed by one member
    Then the pack is offered first
    And the five star member is still in the pack

  Scenario: The writer is told the rating as direction without a handle
    Given an accepted Reference with an editor's reason and 5 stars
    When the run drafts ideas for the rated Reference
    Then the writer's input says the editors gave 5 of 5 stars
    And no connection handle carries the stars
    And the writer's instructions say the rating is never reported

  Scenario: A changed rating makes a rejected idea worth another try
    Given an accepted Reference whose idea was rejected for adding nothing
    When an editor rates it 5 stars
    And the run drafts ideas for the rated Reference
    Then the run records that it tried again because of the new rating

  Scenario: A highly rated Reference with no idea is explained
    Given an accepted Reference rated 5 stars that the newsroom knows nothing about beyond its source
    When the run drafts ideas for the rated Reference
    Then the run record lists it as rated and without an idea because there was nothing to add
    And the curation flag names it and says why

  Scenario: A pending Reference keeps its stars as context and is never a single-item idea
    Given a pending Reference rated 5 stars
    When the signals are read
    Then its stars are available in the pending context
    And the run drafts no idea from it
