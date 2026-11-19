Feature: Agents that wake each other stop at the owner's limit
  Agents wake each other by changing records, so two agents could pass a Story back and forth (PPY-4e7e8b, slice B7 of the always-on agents design). The guard
  keeps the count the Stage Bots already kept and makes it general: the number of wakes caused by an agent's change on a Story since a person last acted on it. The
  limit is the owner's, set per responsibility in the agent policy document (it starts at 5). At the limit nothing more starts for that Story and ONE hard-gate review
  request says so. A person's change to the Story clears the count and opens the next round, so a later loop raises its own request. An agent's own new version wakes
  the other agents' free and paid steps and never the step that wrote it.

  Background:
    Given the site "sample" with its wake gate
    And these agents listen through the gate
      | agent      | responsibility | procedure        | paid  | change          | filter     |
      | writer     | improve        | story.improve    | false | version_created | type=story |
      | critic     | critique       | story.critique   | false | version_created | type=story |
    And the owner has set the loop limit of "improve" and "critique" to 3

  Scenario: Two agents alternating stop at the limit
    When the agents "writer" and "critic" pass the Story "story-1" back and forth, starting with "writer", for 5 saves
    Then the Story "story-1" has been run by agents 3 times since a person acted
    And the agent "critic" was woken 2 times
    And the agent "writer" was woken 1 time
    And 1 hard-gate review request is open for the Story "story-1"
    And the hard-gate request says the loop limit of 3 was reached

  Scenario: The hard gate is raised once
    When the agents "writer" and "critic" pass the Story "story-1" back and forth, starting with "writer", for 5 saves
    And the agent "critic" writes version 7 of the Story "story-1" at "2026-11-18T09:30:00Z"
    Then the agent "writer" was woken 1 time
    And 1 hard-gate review request is open for the Story "story-1"

  Scenario: A person's action lets work continue
    Given the agents "writer" and "critic" pass the Story "story-1" back and forth, starting with "writer", for 5 saves
    When a person writes version 7 of the Story "story-1" at "2026-11-18T10:00:00Z"
    Then the Story "story-1" has been run by agents 0 times since a person acted
    When the agent "writer" writes version 8 of the Story "story-1" at "2026-11-18T10:01:00Z"
    Then the agent "critic" was woken 4 times
    And the Story "story-1" has been run by agents 1 time since a person acted

  Scenario: A later loop raises its own request
    Given the agents "writer" and "critic" pass the Story "story-1" back and forth, starting with "writer", for 5 saves
    And a person wrote version 7 of the Story "story-1" at "2026-11-18T10:00:00Z"
    When the agents "writer" and "critic" pass the Story "story-1" back and forth, starting with "writer", for 5 saves
    Then 2 hard-gate review requests are open for the Story "story-1"

  Scenario: An agent's own version does not re-wake it
    When the agent "writer" writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    Then the agent "writer" was woken 0 times
    And the agent "critic" was woken 1 time

  Scenario: An agent never re-runs its own paid step on its own output
    Given the paid agent "fact-check" also listens
    When the agent "fact-check" writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    Then the site's wait timers hold no wait for "fact-check" on "story-1"
    And the agent "writer" was woken 1 time

  Scenario: Another agent's paid step is woken by an agent's version
    Given the paid agent "fact-check" also listens
    When the agent "writer" writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    Then the site's wait timers hold a wait for "fact-check" on "story-1"

  Scenario: A different limit for a different agent
    Given the owner has set the loop limit of "critique" to 1
    When the agent "writer" writes version 2 of the Story "story-1" at "2026-11-18T09:05:00Z"
    And the agent "writer" writes version 3 of the Story "story-1" at "2026-11-18T09:06:00Z"
    Then the agent "critic" was woken 1 time
    And 1 hard-gate review request is open for the Story "story-1"
