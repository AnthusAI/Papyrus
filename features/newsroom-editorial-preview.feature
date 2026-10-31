@brand-agnostic
Feature: Editorial findings on the article preview
  Editors see editorial findings where readers would see the words: on the
  rendered preview as well as in the markup. They can open a finding where it is
  marked, ask for rewrite options, pick one, or dismiss the finding, and they can
  select any passage of the preview and ask for rewrites of it. These scenarios
  run in demo mode, whose editorial checks flag a few stock phrases.

  Checks run by themselves whenever the content changes, so editors never have to
  ask: findings mark the body and fill the panel a moment after typing stops, and
  again after each save. The server also checks every saved version, and never
  checks identical content twice.

  Rule: An editor can still check on demand

    Background:
      Given I open a new article at 1400 by 1000
      When I enter the article body:
        """
        # Launch notes

        Our caching layer is **game-changing** for teams. Builds finish in 4 minutes instead of 9.

        We utilize a shared volume.
        """
      And I check the article's editorial policies

    Scenario: Findings are marked in the markup and on the preview
      Then the body editor marks "game-changing" and "utilize"
      And the preview marks "game-changing" and "utilize"

    Scenario: Pick a rewrite for a finding from the preview
      When I open the preview finding on "game-changing"
      And I ask for rewrite options in the preview
      Then the preview shows rewrite options
      When I use the first rewrite option
      Then the article body should contain "Our caching layer cuts build times for teams."
      And the preview no longer marks "game-changing"

    Scenario: Use a deterministic fix from the preview
      When I open the preview finding on "utilize"
      And I use the suggested replacement "use"
      Then the article body should contain "We use a shared volume."

    Scenario: Dismiss a finding from the preview
      When I open the preview finding on "utilize"
      And I dismiss the finding
      Then the preview no longer marks "utilize"
      And the body editor no longer marks "utilize"

    Scenario: Rewrite a passage selected on the preview
      When I select "Builds finish in 4 minutes" on the preview
      And I ask for rewrites of the preview selection
      Then the preview shows rewrite options for "Builds finish in 4 minutes instead of 9."

  Rule: Checks run automatically whenever the content changes

    Background:
      Given I open a new article at 1400 by 1000

    Scenario: Editing shows inline marks without clicking Check
      When I enter the article body:
        """
        Our caching layer is **game-changing** for teams.

        We utilize a shared volume.
        """
      Then the editorial findings appear by themselves
      And the body editor marks "game-changing" and "utilize"

    Scenario: Editing again checks the new text
      When I enter the article body "We utilize a shared volume."
      Then the editorial findings appear by themselves
      When I enter the article body "We use a shared volume, which is game-changing."
      Then the body editor marks "game-changing"
      And the body editor no longer marks "utilize"

    # info is the mildest severity: it is marked and listed, never a crash and never a publishing warning.
    Scenario: An info finding is marked in the body and listed as something to consider
      When I enter the article body "We utilize a shared volume."
      Then the editorial findings appear by themselves
      And the body editor marks "utilize" with the "info" severity
      And the findings panel lists "plain-words" as "Consider"

    Scenario: Content that has not changed is not checked again
      When I enter the article body "We utilize a shared volume."
      Then the editorial findings appear by themselves
      And the editor asked for exactly 1 check after waiting 5 seconds

    Scenario: Saving the article has the server check the saved version
      When I enter the article title "Volumes"
      And I enter the article body "We utilize a shared volume."
      Then the editorial findings appear by themselves
      When I save the article draft
      Then the server was asked to check the saved version
      And the editor asked for exactly 1 check after waiting 5 seconds

    Scenario: A provider failure shows an error instead of an empty result
      Given the editorial checks provider is down
      When I enter the article body "We utilize a shared volume."
      Then the findings panel shows the error "language-model provider did not respond"
      And the editor asked for exactly 1 check after waiting 5 seconds
      And the body editor no longer marks "utilize"

    Scenario: Findings at a phone width
      Given I open a new article at 390 by 844
      When I enter the article body:
        """
        Our caching layer is **game-changing** for teams.

        We utilize a shared volume.
        """
      Then the editorial findings appear by themselves
      And I save a screenshot named "autorun-390"

    Scenario: Findings at a desktop width
      Given I open a new article at 1440 by 900
      When I enter the article body:
        """
        Our caching layer is **game-changing** for teams.

        We utilize a shared volume.
        """
      Then the editorial findings appear by themselves
      And I save a screenshot named "autorun-1440"

    Scenario: A provider failure at a phone width
      Given I open a new article at 390 by 844
      And the editorial checks provider is down
      When I enter the article body "We utilize a shared volume."
      Then the findings panel shows the error "language-model provider did not respond"
      And I save a screenshot named "autorun-error-390"

  Rule: The findings surfaces are flat tones, not outlined boxes

    Editors read findings in the panel, on each finding card and in the popover
    that opens from a mark. Following the newsroom's no-borders rule, all three
    are rounded rectangles in flat background tones. A finding's severity is
    said with an icon and a word, never by colour alone.

    Scenario: No findings surface has a border
      Given I open a new article at 1400 by 1000
      When I enter the article body:
        """
        Our caching layer is **game-changing** for teams.

        We utilize a shared volume.
        """
      And I check the article's editorial policies
      Then nothing in the findings panel has a border or an outline
      And every severity in the findings panel has an icon and a word
      When I open the preview finding on "utilize"
      Then nothing in the findings popover has a border or an outline

    Scenario: The editor demo page logs no console errors
      Given I open a new article at 1400 by 1000
      When I reload the page recording every console error
      Then the page logged no console errors
