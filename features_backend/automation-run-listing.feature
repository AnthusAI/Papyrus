Feature: An editor can see everything a story-stage automation did
  A story-stage automation, such as the fact-check bot that starts when a story enters the reporting
  stage, starts one run for each story, stage and version. Editors read those runs with the same
  command they use for a monitor automation. Each run says which tools the procedure called, by name
  and count, so an editor can verify the bot really read what it was meant to read. A run whose story
  has since been deleted says so instead of pointing at a story that is gone, and the cost line says
  what it adds up.

  Background:
    Given a site backend with the fact-check automation that starts when a story enters reporting
    And the fact-check bot has run on the story "story-a" and on the story "story-gone"

  Scenario: The runs a story entering the stage started are listed
    When an operator runs "automations runs --id distinctive.ruling.fact-check"
    Then the output lists 2 runs started because a story entered reporting
    And the run for "story-a" shows its run id

  Scenario: A run says which tools the procedure used
    When an operator runs "automations runs --id distinctive.ruling.fact-check"
    Then the run for "story-a" says it used "papyrus_fetch_pdf_text x2, papyrus_story_version x1"
    And the run for "story-gone" says no tools were recorded

  Scenario: A run whose story was deleted says so
    When an operator runs "automations runs --id distinctive.ruling.fact-check"
    Then the run for "story-gone" says the story was deleted
    And the run for "story-a" does not say the story was deleted

  Scenario: The cost line says what it adds up
    When an operator runs "automations runs --id distinctive.ruling.fact-check"
    Then the output says "$0.0100 total across 1 run with a recorded cost (1 of 2 listed runs; an estimate)"
