Feature: Bots act as a story moves between stages
  A publication can name a procedure to run when a story enters a stage. An automation says which stage it fires on
  (onStage) and where the story goes when the bot is done (nextStage). The engine starts the procedure with the story,
  the version that entered the stage and a run key; the procedure writes a new version and returns its id. The engine,
  not the procedure, moves the story on, labelled as a bot action by the automation. A person is never a stage: when a
  person is wanted, because a bot failed, held the story, or the chain ran too long, the engine raises a review request.
  The example chain is reporting, then the fact-check bot, then copywriting, then the copy-edit bot, then typesetting,
  where no bot waits.

  Scenario: Entering a stage starts the procedure with the story, version and run key
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    Then the bot's procedure starts once
    And its input names the story, its version, the stage, the run key, the automation id and hop 1
    And the run is recorded on a claim row for that story, stage and version

  Scenario: The engine's own input fields win over the automation's static input
    Given a story in the copywriting stage and a copywriting bot whose static input tries to set the story and the hop
    When the story's stage-entry triggers are delivered
    Then the bot's input carries the real story and hop 1

  Scenario: Delivering the same event twice starts one run
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered twice
    Then the bot's procedure starts once
    And the second delivery is reported as a duplicate
    And the story counts one bot hop

  Scenario: A new version in the same stage is a new claim
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And a person saves a new version and the triggers are delivered again
    Then the bot's procedure starts twice

  Scenario: A story in a stage no automation watches starts nothing
    Given a story in the reporting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    Then no bot procedure starts

  Scenario: An automation at its concurrency limit defers the start
    Given a story in the copywriting stage and a copywriting bot that may run one at a time with another story already running
    When the story's stage-entry triggers are delivered
    Then no bot procedure starts
    And the outcome is deferred because of the concurrency limit

  Scenario: A finished run moves the story on as a bot action
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And the procedure writes a new version and finishes
    Then the story is in the typesetting stage
    And the story's trail names automation:distinctive.copywriter as the actor of the move
    And the story keeps a record that automation:distinctive.copywriter moved it to typesetting with a new version
    And the new version is labelled as a bot action of distinctive.copywriter

  Scenario: A bot that finds nothing to change returns the version it received and the story still advances
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And the procedure returns the version it received with extra findings
    Then the story is in the typesetting stage
    And the story's trail says distinctive.copywriter made no changes
    And the story keeps a record that automation:distinctive.copywriter moved it to typesetting with no changes
    And no version is labelled as a bot action
    And no review request is raised

  Scenario: Without a next stage the story stays
    Given a story in the copywriting stage and a copywriting bot with no next stage
    When the story's stage-entry triggers are delivered
    And the procedure writes a new version and finishes
    Then the story is in the copywriting stage

  Scenario: A held story stays and a flag review request carries the reason
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And the procedure writes a new version and holds the story because "two sources disagree"
    Then the story is in the copywriting stage
    And one flag review request raised by automation:distinctive.copywriter mentions "two sources disagree"

  Scenario: A failed or timed-out run leaves the story and flags the error
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And the run fails with "timed out after 600 s"
    Then the story is in the copywriting stage
    And one flag review request raised by automation:distinctive.copywriter mentions "timed out after 600 s"

  Scenario: A run that returns no version leaves the story and flags it
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And the procedure finishes without returning a version
    Then the story is in the copywriting stage
    And a flag review request exists

  Scenario: A story someone else moved while the bot ran is not moved again
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story's stage-entry triggers are delivered
    And a person moves the story to illustration while the bot runs
    And the procedure writes a new version and finishes
    Then the story is in the illustration stage

  Scenario: The example chain runs each bot once and stops where no bot waits
    Given a story in the reporting stage and the fact-check and copy-edit bots
    When the story's stage-entry triggers are delivered
    And the procedure writes a new version and finishes
    And the procedure writes a new version and finishes
    Then the story is in the typesetting stage
    And the bots ran in order fact-check then copy-edit, at hops 1 and 2
    And no third procedure started

  Scenario: A person moving a story into a stage fires that stage's bot
    Given a story in the reporting stage and the fact-check and copy-edit bots
    When a person moves the story to copywriting and the triggers are delivered
    Then only the copy-edit bot starts

  Scenario: A monitor-triggered procedure creates a story at reporting through a tool and its completed run starts the reporting bot once
    Given a story in the reporting stage and the fact-check and copy-edit bots
    And a procedure run started by a monitor created that story through a tool, so nothing delivered its triggers
    When the run completes and its output names the story
    Then the fact-check bot starts exactly once
    And a second look at the same completed run starts nothing more
    And a run that failed fires no trigger

  Scenario: At the hop limit nothing starts and a hard gate is raised once
    Given a story in the copywriting stage and a copywriting bot limited to 2 hops
    When the story has already had 2 bot hops
    And the story's stage-entry triggers are delivered twice
    Then no bot procedure starts
    And the story is in the copywriting stage
    And exactly one hard gate review request says "bot hop limit reached"

  Scenario: The hop limit is 5 unless the record says otherwise
    Given a story in the copywriting stage and a copywriting bot that moves stories to typesetting
    When the story has already had 5 bot hops
    And the story's stage-entry triggers are delivered
    Then no bot procedure starts

  Scenario: An editor creates a stage-entry automation from the command line fields
    When an operator describes a bot with on-stage copywriting, next-stage typesetting and max-hops 3
    Then the record is an event automation firing when a story enters copywriting, then moving it to typesetting, with at most 3 hops
    And a stage the publication does not have is refused
    And a static input that uses placeholders is refused
