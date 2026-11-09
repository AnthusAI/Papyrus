Feature: Editors take a published Story down safely and bring it back
  `papyrus stories move --stage spiked` changes only the board: the page stays live. `papyrus ops content unpublish` removes the data but leaves the
  Story in copywriting with no plan and no record of what happened. `papyrus stories withdraw` is the safe whole. It prints the exact plan first: the
  Story page and its Markdown twin, every index page that lists it, and the invalidation paths with their count and what they cost at most (the first
  1000 paths a month are free, then 0.005 USD each). It refuses a plan above the per-call cap of 25 paths unless the editor forces that one call, and
  with more than 5 paths it is a dry run until the editor repeats it with --run. Then it unpublishes the Story, has the site take the pages away, moves
  the board stage to spiked, records who withdrew which version when, why, and from which stage, and purges exactly the planned paths. `stories restore`
  republishes the withdrawn version, puts the stage back to published, clears the record and purges the same pages. Withdrawing a withdrawn Story says
  so and changes nothing. The old address shows the site's 404 page, because static hosting cannot answer 410. Every client here is an in-memory
  stand-in; nothing reaches a real site or AWS.

  Background:
    Given a published Story "file:articles/a1.md" on a site with four articles in two pages of the articles section

  Scenario: The plan lists the exact pages, the paths, their count and the cost
    When an editor withdraws the Story as a dry run
    Then the plan lists the Story page and its Markdown twin "articles/a1/index.html" and "articles/a1/index.md"
    And the plan lists the index pages "index.html" and "articles/index.html"
    And the plan lists 9 invalidation paths and says they cost at most 0.045 USD at 0.005 USD each
    And the plan lists the path "/articles/a1/index.md"
    And nothing was written and nothing was purged

  Scenario: A plan of more than 5 paths is a dry run until the editor says to run it
    When an editor withdraws the Story without --run
    Then the Story is still published
    And the output says to repeat the command with --run

  Scenario: Withdrawing removes the published rows, spikes the card and records the withdrawal
    When an editor "Ryan" withdraws the Story with the reason "published by mistake"
    Then no published row remains for the Story
    And the Story's board stage is "spiked"
    And the Story's withdrawal record names version 1, "Ryan", the reason "published by mistake" and the previous stage "published"
    And the site was asked to take the Story's pages away

  Scenario: Exactly the planned paths are purged
    When an editor "Ryan" withdraws the Story with the reason "published by mistake"
    Then the withdrawal asked the edge to purge exactly the 9 planned paths

  Scenario: A withdrawal plan above the cap is refused
    Given the site allows at most 5 paths in one call
    When an editor "Ryan" withdraws the Story with the reason "too wide"
    Then the withdrawal is refused as over the cap
    And the Story is still published
    And the withdrawal asked the edge for no purge

  Scenario: The editor can force one call above the cap
    Given the site allows at most 5 paths in one call
    When an editor withdraws the Story forcing up to 9 paths
    Then the Story's board stage is "spiked"

  Scenario: A Story that is not published cannot be withdrawn
    Given the Story is a draft that was never published
    When an editor tries to withdraw the Story
    Then the withdrawal is refused because the Story is not published
    And the Story's board stage is not "spiked"

  Scenario: Withdrawing a withdrawn Story says so and changes nothing
    Given the Story was withdrawn
    When an editor withdraws the Story again
    Then the output says the Story is already withdrawn
    And nothing new was purged

  Scenario: Restoring brings the Story back
    Given the Story was withdrawn
    When an editor restores the Story
    Then the Story is published again with the board stage "published"
    And the Story has no withdrawal record
    And the withdrawal asked the edge to purge exactly the 9 planned paths

  Scenario: Restoring a Story that was never withdrawn is refused
    When an editor tries to restore the Story
    Then the restore is refused because nothing was withdrawn

  Scenario: Moving a Story to spiked is board-only and the help points to withdraw
    When an editor reads the help of "stories move"
    Then the help says the move is board-only
    And the help points to "stories withdraw" to take a page down
