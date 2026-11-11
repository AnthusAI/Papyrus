@backend @stories-list
Feature: `papyrus stories list` lists the same Stories the Stories board shows
  An editor or an AI agent asks `papyrus stories list --stage <stage>` what is in a column before filing something new or moving it. The list
  must answer for every Story of that stage, however it was filed, and show one line per Story. A Story's newest version is its head: it is
  `current` once it has been published and `draft` until then, so every Story filed from the CLI or the console and not yet published is a
  draft. An older version that was replaced is `superseded` and is never a Story of its own. The Stories board filters the same way. Nothing
  here reaches a real site.

  Scenario: A Story that was never published is listed in its stage
    Given a newsroom with a draft Story in the idea stage and a published Story
    When an agent lists the Stories in the idea stage
    Then the draft Story is listed once
    And the total says one of one

  Scenario: A replaced version is not a Story of its own
    Given a newsroom with a Story whose first version was replaced by a second in the reporting stage
    When an agent lists the Stories in the reporting stage
    Then the Story is listed once, as its second version
    And its first version is not listed

  Scenario: A draft saved over a published version is one Story
    Given a newsroom with a Story that has a published version and a newer draft in the same stage
    When an agent lists the Stories in that stage
    Then the Story is listed once, as the newer draft

  Scenario: The count says how many Stories matched, not how many lines were printed
    Given a newsroom with three draft Stories in the idea stage
    When an agent lists the Stories in the idea stage with a limit of two
    Then two Stories are listed and the total says two of three
