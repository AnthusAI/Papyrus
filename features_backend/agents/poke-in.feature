Feature: Poking in: pause, resume and wake now
  A person steps into what the agents are doing with three operations, each one row of the operation table, so the newsroom's Automation page and
  `papyrus agents pause|resume|wake` ask for the same thing by the same name and get the same answer.

  Pausing is a new version of the site's agent policy, with who, when and why. The runner reads the policy at the start of every run, so the pause stops
  the next run: the wake still arrives, and its run record says "nothing to do" and why. Resuming is another version, and it starts the agent again. Wake now
  sends one agent's latest wake for one subject again, through the site's wake queue, and it runs once: the run re-reads the subject as it is now.

  Redirect and undo are not built yet.

  Background:
    Given a site whose announce agent drafts at the rung "prepare"

  Scenario: Pausing the announce agent stops its next draft
    Given Ada paused "announce" in the newsroom because "Checking the X drafts"
    When Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    Then the announce agent drafted nothing
    And the stopped run for "story-1" says "announce is paused: Checking the X drafts"

  Scenario: Resuming the announce agent starts drafts again
    Given Ada paused "announce" in the newsroom because "Checking the X drafts"
    And Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    When Ada resumes "announce" in the newsroom because "Drafts checked"
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-1" 1 time
    When Story "story-2" is rated 5 stars
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-2" 1 time

  Scenario: A pause and a resume record who, when and why
    When Ada paused "announce" in the newsroom because "Checking the X drafts"
    Then the pauses show "announce" paused by "ada@example.test" because "Checking the X drafts"
    And the policy version the pause made records "ada@example.test" and the reason "Checking the X drafts"
    When Ada resumes "announce" in the newsroom because "Drafts checked"
    Then the pauses show "announce" running
    And the policy version the resume made records "ada@example.test" and the reason "Drafts checked"

  Scenario: Wake now runs the agent once for the subject
    Given Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    When Edie wakes "announce" now for "story-1" in the newsroom because "The guidelines changed"
    And the site's wake queue is delivered
    And the same wake is delivered again
    Then the announce agent drafted for "story-1" 2 times
    And the newest run for "story-1" says it was woken by "edie@example.test" because "The guidelines changed"

  Scenario: Wake now for a subject the agent was never woken for says so and sends nothing
    When Edie wakes "announce" now for "story-9" in the newsroom because "Try it"
    Then the wake is refused as not found, saying "announce has never been woken for story-9"
    And the site's wake queue is empty

  Scenario: Wake now does not get past a pause
    Given Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    And Ada paused "announce" in the newsroom because "Checking the X drafts"
    When Edie wakes "announce" now for "story-1" in the newsroom because "The guidelines changed"
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-1" 1 time

  Scenario: An agent may not pause, resume or wake
    When an agent asks the command line to pause "announce" because "I am stuck"
    Then the command line refuses it as "blocked" and the policy is unchanged
    When an agent asks the command line to wake "announce" now for "story-1" because "Again"
    Then the command line refuses it as "human_required" and the site's wake queue is empty

  Scenario Outline: Every poke-in works the same in the newsroom and on the command line
    Given Story "story-1" is rated 4 stars
    And the site's wake queue is delivered
    When Ada pauses "announce" <door> because "Checking the X drafts"
    And Story "story-2" is rated 5 stars
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-2" 0 times
    When Ada resumes "announce" <door> because "Drafts checked"
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-2" 1 time
    And the resume answered with policy version 3 and one caught-up wake for "story-2"
    When Edie wakes "announce" now for "story-1" <door> because "The guidelines changed"
    And the site's wake queue is delivered
    Then the announce agent drafted for "story-1" 2 times

    Examples:
      | door                 |
      | in the newsroom      |
      | on the command line  |

  Scenario: Every request poke-in sends to the site's API is one the site's GraphQL schema accepts
    The fake site above answers whatever is asked, so a request AppSync would refuse could pass every scenario here and fail on a real site. The run index
    reads a resume and wake now make, the run record that keeps its wake, and the two doors the command line sends to are checked against the schema Amplify
    generates from amplify/data/schema.ts.
    When the poke-in requests are built against a recording site API
    Then every poke-in request is accepted by the GraphQL schema Amplify generates from the data schema
