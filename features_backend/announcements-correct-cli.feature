Feature: papyrus announcements correct: a correction typed at the command line is checked like a new Delivery and written as the next generation
  When a post went out with a mistake, an editor corrects it with one command: the Delivery that went and the new words. The words go through the same checks a new
  Delivery's words get (for an X post: its length, no invented links or tags, and every claim against the Story) before anything is written. If they pass, the
  new Delivery is written as the next generation under the review the old one had, the old one is marked superseded, and the supersedes link joins them. The command
  writes unless it is given --dry-run. Every refusal is a plain sentence: a Delivery that never went is edited and not corrected, an attempt with no answer is settled
  first, and a different correction that already exists is a conflict, so there is never a second live Delivery. The command never sends anything and never deletes the
  old post; the checks use a fake judge and the catalog is in memory.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text                                  |
      | x       | handle-1 | none     | A look at how slow water shapes stone |
    And one worker serves the channel "x" account "handle-1"
    And the fact check supports what the Story titled "A look at how slow water shapes stone" says

  # --- the command writes the correction ---------------------------------------------------------------------------------------------------------

  Scenario: A Delivery that went is corrected with one command
    Given the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command succeeds
    And the command's result names generation 2 which supersedes generation 1 of "x" "handle-1"
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And generation 2 of "x" "handle-1" has these words in S3 "Slow water shapes stone, corrected"
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation
    And the live Delivery of "x" "handle-1" is generation 2
    And exactly 1 post was made

  Scenario: The new Delivery goes under the review the old one had
    Given the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command's result says the review is "none" and the checks "length, markup, facts" passed

  Scenario: A dry run checks the input and writes nothing
    Given the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct --dry-run" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command succeeds
    And the command's result says it was a dry run
    And the catalog holds 1 Delivery

  # --- the words are checked like a new Delivery's ----------------------------------------------------------------------------------------------

  Scenario: Words that claim something the Story does not say are refused and nothing is written
    Given the worker sends the Delivery "x" "handle-1"
    And the fact check supports nothing
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command is refused as "checks_failed" saying "This claim is not in the Story"
    And the catalog holds 1 Delivery
    And the Delivery "x" "handle-1" generation 1 is "sent"

  Scenario: Words that are too long for the post are refused
    Given the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with a text of 400 letters
    Then the command is refused as "checks_failed" saying "Too long for X"
    And the catalog holds 1 Delivery

  Scenario: Words with a link of their own are refused
    Given the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone https://elsewhere.example/a"
    Then the command is refused as "checks_failed" saying "has its own link"
    And the catalog holds 1 Delivery

  Scenario: Empty words are refused
    Given the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text " "
    Then the command is refused as "checks_failed" saying "empty"
    And the catalog holds 1 Delivery

  # --- the refusals are plain sentences ---------------------------------------------------------------------------------------------------------

  Scenario: A Delivery that never went is edited, not corrected
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command is refused as "constraint_conflict" saying "edited, not corrected"
    And the catalog holds 1 Delivery

  Scenario: A Delivery with an attempt that has no answer is settled first
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command is refused as "constraint_conflict" saying "settled before a correction is made"
    And the catalog holds 1 Delivery

  Scenario: A different correction that already exists is a conflict
    Given the worker sends the Delivery "x" "handle-1"
    And the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, first correction"
    When the command "announcements correct" is run on generation 1 of "x" "handle-1" with the text "Slow water shapes stone, second correction"
    Then the command is refused as "constraint_conflict" saying "different words"
    And the catalog holds 2 Deliveries
    And generation 2 of "x" "handle-1" has these words in S3 "Slow water shapes stone, first correction"
    And the live Delivery of "x" "handle-1" is generation 2

  Scenario: The same correction again finishes the correction and makes no second Delivery
    Given the worker sends the Delivery "x" "handle-1"
    And the command "announcements correct" is run on the Delivery "x" "handle-1" with the text "Slow water shapes stone, corrected"
    When the command "announcements correct" is run on generation 1 of "x" "handle-1" with the text "Slow water shapes stone, corrected"
    Then the command succeeds
    And the catalog holds 2 Deliveries

  Scenario: A Delivery that does not exist is not found
    When the command "announcements correct" is run on the Delivery id "nowhere#x#handle-1#g1" with the text "Slow water shapes stone, corrected"
    Then the command is refused as "not_found" saying "No Delivery"
