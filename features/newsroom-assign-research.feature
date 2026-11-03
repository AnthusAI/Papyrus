@brand-agnostic
Feature: An editor assigns research from the Story page and sees it through to a packet
  On a Story's Messages view the Work section starts with an Assign research box: a text area for what the research should find out and one button with an icon.
  There is no dropdown and no boxed outline, and nothing is said by colour alone. It is there at every stage of the Story. It makes the same research
  assignment as the papyrus stories assign-research command, which a worker runs without anyone at a terminal. An empty direction is refused in words before
  anything is written. The Work section then shows each research assignment with the editor's direction, its state in words and with an icon (waiting, running,
  finished or failed with the reason), when it was made and, once finished, its packet: the summary, the recommended angle, each claim with links to the sources it
  cites, where the sources disagree, the open questions and a "Could not verify" list when the packet has one, each entry labelled Needs a check, Rejected or Not checked in words and with an icon, with its reasons in plain words, and a fact check line made from the counts. The box has no visible label and no outline, even when it has focus. The packet is read from the assignment and never
  added to a message thread. These scenarios run in demo mode with in-memory data, where no worker runs, so a new assignment stays waiting.

  Scenario: The box is there and is a text area and one button
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's Messages view
    Then the Work section should start with the Assign research box
    And the box should have one text area, one button with an icon, and no dropdown
    And the box should have no border or outline

  Scenario: An empty direction is refused in words
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's Messages view
    And I press Assign research with nothing written
    Then the box should say "Write what the research should find out before you send it."
    And no new research assignment should appear

  Scenario: A direction makes a waiting research assignment
    Given I open the demo story that has no Reference at 390 by 844
    When I open the story's Messages view
    And I write the direction "Find the court rulings on model output" and press Assign research
    Then the box should say that the research was assigned
    And the Work section should show a research assignment that is waiting, with the direction "Find the court rulings on model output"

  Scenario: Every state shows in words and with an icon
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's Messages view
    Then the research assignments should be shown as waiting, running, failed and finished, each with a word and an icon
    And the failed assignment should give its reason "no search provider answered"

  Scenario: A finished assignment shows its packet with linked sources and what could not be verified
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's Messages view
    Then the finished assignment should show the packet summary and the recommended angle
    And its claims should link to the sources they cite
    And the packet should list where the sources disagree and the open questions
    And the packet should list "Could not verify" with a claim and its reasons
    And each unverified claim should be labelled "Needs a check", "Rejected" or "Not checked" with an icon, and its reasons in plain words
    And the fact check line should read "12 verified, 8 need a check, 8 rejected; 23 rest on one site"

  Scenario: The Messages view does not scroll sideways on a phone
    Given I open the demo story that is based on a Reference at 390 by 844
    When I open the story's Messages view
    Then the page should not scroll sideways
