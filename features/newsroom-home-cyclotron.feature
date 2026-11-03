Feature: The newsroom home page shows the Cyclotron classifier behind this site's predictions
  At the top right of the newsroom home page (above the list on a phone) a panel says what the classifier is doing: when it last changed or was
  cycled, its latest evaluation number and what that number was measured on, and counts such as the reviewed labels. It shows this site's
  own classifier only. It says only what the Cyclotron's status snapshot says: it never implies learning that did not happen, a missing number
  says "Not measured yet", and a site with no snapshot gets a plain sentence, never a skeleton that waits for ever. Votes made after a snapshot
  are not in it, so the panel shows when the snapshot is from. History over time and the supporting questions behind a decision wait for the
  Cyclotron's richer report operation, which is not published; nothing stands in for them here.

  Background:
    Given a newsroom home page with synthetic classifier snapshots at 375 and 1440 pixels

  Scenario: A snapshot is shown in words, top right on a desktop and above the list on a phone
    When the editor opens the home page and the classifier has cycled twice with 41 reviewed labels
    Then the panel says the classifier has cycled twice and when it last changed
    And the panel gives the agreement with reviewers as a percentage and says it was measured on the reviews the Cyclotron selected
    And the panel counts the reviewed labels and the decisions awaiting review
    And the panel says when the snapshot is from and that votes after it are not included yet
    And the panel is in the top right of the header on a desktop and between the title and the list on a phone
    And nothing in the panel has a border, every icon is a Lucide icon, it has no dropdown, and nothing scrolls sideways

  Scenario: A site whose classifier has never cycled is told so plainly
    When the editor opens the home page and the snapshot has no cycle, no last change and no reviewed labels
    Then the panel says it has not cycled yet
    And the agreement says "Not measured yet" and shows no percentage
    And no sentence in the panel implies that the classifier learned anything

  Scenario: A site with no snapshot gets a sentence, not a skeleton
    When the editor opens the home page and the Cyclotron has not reported on this site's classifier yet
    Then the panel says the Cyclotron has not reported on this site's classifier yet, with no skeleton and no empty field
    And when the status cannot be read the panel says so in one sentence and the feed is still shown
    And while the status is being read the panel says it is being read

  Scenario: A page without the status read has no panel
    When the editor opens a home page that has no classifier status source
    Then there is no classifier panel
