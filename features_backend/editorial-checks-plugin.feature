@backend @editorial-checks
Feature: Editorial checks plugin
  Editors check an article against the publication's editorial policies and ask
  for rewrite options without leaving the newsroom. Admins keep the policies in
  Papyrus: they start from a starter pack, write their own, try them on sample
  text, and recalibrate them from editors' decisions. Limatus does the checking;
  Papyrus owns the policies, the settings and the decisions.

  Background:
    Given a site with the editorial checks plugin and these policies:
      | key      | scope       | severity | enabled | phrase        |
      | no-hype  | publication | warn     | yes     | game-changing |
      | jargon   | engineering | info     | yes     | synergy       |
      | retired  | publication | error    | no      | going forward |

  Scenario: Check an article against publication and section policies
    When an editor checks "This game-changing synergy ships going forward." in section "engineering"
    Then the check result is a valid Limatus "check-result-v1" document
    And the findings are for policies "no-hype, jargon"

  Scenario: Section policies apply only to their section
    When an editor checks "This game-changing synergy ships." in section "culture"
    Then the findings are for policies "no-hype"

  Scenario: A section policy replaces the publication policy with the same key
    Given the "engineering" section also has a "no-hype" policy for "revolutionary"
    When an editor checks "A game-changing, revolutionary release." in section "engineering"
    Then the findings are for policies "no-hype"
    And the "no-hype" finding's excerpt is "revolutionary"

  Scenario: Settings choose the lanes, the models and a deadline under the API timeout
    Given the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then Limatus was asked to run the classifier with a 12 second deadline
    And the classifier lane status is reported

  Scenario: Editors' decisions with text travel as examples for the classifier
    Given editors have recorded 3 decisions with text on policy "no-hype"
    And the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then Limatus received 3 past decisions as examples

  Scenario: Ask for rewrite options for a finding
    Given the rewrite model will propose "This release cuts build times."
    When an editor checks "This game-changing release." in section "engineering"
    And the editor asks for rewrites of the "no-hype" finding
    Then there is 1 rewrite option "This release cuts build times."

  Scenario: Ask for rewrite options for a selection with a note
    Given the rewrite model will propose "Builds take 4 minutes."
    When the editor selects "Builds now finish in four minutes." in "Builds now finish in four minutes." and asks for rewrites with the note "shorter"
    Then there is 1 rewrite option "Builds take 4 minutes."

  Scenario: Import a starter pack once
    When an admin imports the starter pack "ai-writing-tells"
    Then 24 policies were created with scope "publication"
    And importing "ai-writing-tells" again creates 0 policies

  Scenario: Try a policy on sample text without saving it
    When an admin tries a policy with phrase "leverage" on "We leverage caching."
    Then the try result has 1 finding with excerpt "leverage"
    And no policy was saved

  Scenario: Draft classifier questions for a policy written in prose
    Given the rewrite model will draft the question "Does the target sentence hype the product?"
    When an admin drafts questions for "No hype" with guidance "Show evidence instead of hype."
    Then the draft has 1 sentence detector

  Scenario: Recalibrate classifier policies from editors' decisions
    Given policy "no-hype" also has a sentence classifier detector "hype-judge"
    And editors have recorded 60 decisions on "no-hype" detector "hype-judge"
    When an admin recalibrates the policies
    Then policy "no-hype" detector "hype-judge" has an "isotonic" calibration
    And policy "no-hype" is now version 2

  Scenario: Import a style profile as publication policies
    When an operator imports the style profile "features_backend/fixtures/editorial-checks/style-profile.yml"
    Then the site has the policies "avoid-lexicon, banned-phrases, house-checks, tone" with scope "publication"
    And importing the same profile again creates 0 policies

  Scenario: Check a draft from the command line against a policy-pack file
    Given a policy-pack file whose policy "no-hype" flags "game-changing"
    When an operator runs papyrus editorial check on a draft saying "This is game-changing."
    Then the printed check result has a "no-hype" finding on "game-changing"
