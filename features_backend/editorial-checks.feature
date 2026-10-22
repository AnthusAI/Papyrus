@backend @editorial-checks
Feature: Editorial checks
  Editors check an article against the publication's editorial policies and ask
  for rewrite options without leaving the newsroom. Admins keep the policies in
  Papyrus: they start from a starter pack, write their own, try them on sample
  text, and recalibrate them from editors' decisions. Humanus does the checking;
  Papyrus owns the policies, the settings and the decisions.

  Background:
    Given a site with editorial checks and these policies:
      | key      | scope       | severity | enabled | phrase        |
      | no-hype  | publication | warn     | yes     | game-changing |
      | jargon   | engineering | info     | yes     | synergy       |
      | retired  | publication | error    | no      | going forward |

  Scenario: Editorial checks run by default when the publication stored no settings
    Given the publication has stored no editorial check settings
    When an editor checks "This game-changing release." in section "engineering"
    Then the findings are for policies "no-hype"

  Scenario: A publication turns editorial checks off in its stored settings
    Given the editorial check settings turn editorial checks off
    When an editor checks "This game-changing release." in section "engineering"
    Then the check is refused because editorial checks are turned off
    And Humanus was not asked to check

  Scenario Outline: The function finds its GraphQL field in the AppSync event Amplify sends
    When AppSync invokes the function with the field in "<place>"
    Then the function routes to "checkItemVersion"

    Examples:
      | place              |
      | the top level      |
      | the info object    |

  Scenario: Check an article against publication and section policies
    When an editor checks "This game-changing synergy ships going forward." in section "engineering"
    Then the check result is a valid Humanus "check-result-v1" document
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
    Then Humanus was asked to run the classifier with a 12 second deadline
    And the classifier lane status is reported

  Scenario: Editors' decisions with text travel as examples for the classifier
    Given editors have recorded 3 decisions with text on policy "no-hype"
    And the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then Humanus received 3 past decisions as examples

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

  Scenario Outline: Import a writing-standard starter pack
    When an admin imports the starter pack "<pack>"
    Then <count> policies were created with scope "publication"

    Examples:
      | pack           | count |
      | asd-ste100     | 9     |
      | plain-language | 14    |

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

  Scenario: The function resolves its provider keys from Amplify secrets
    Given the function environment has Amplify secret placeholders for "TYPESAFE_API_KEY" and "OPENAI_API_KEY"
    And SSM holds a value for "TYPESAFE_API_KEY" only
    When the function prepares its provider keys
    Then "TYPESAFE_API_KEY" is the value stored in SSM
    And "OPENAI_API_KEY" is not set, so rewrite suggestions report that they are not configured

  # PPY-2c4b56: a publication without a mission still gets its rule-based copy checks.
  Scenario: No current mission: rule checks run, judgment checks are skipped
    Given the publication has no current mission
    And the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then the findings are for policies "no-hype"
    And Humanus was asked to run without the classifier
    And the classifier lane is skipped because the publication has no mission

  Scenario: The skip is stored with the checked version
    Given the publication has no current mission
    And the editorial check settings turn the classifier on with a 12 second deadline
    When the saved version of a story with "This game-changing release." is checked
    Then the stored check run records the classifier lane as skipped

  Scenario: One current mission: judgment checks run as before
    Given the publication has one current mission
    And the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then Humanus was asked to run the classifier with a 12 second deadline
    And the classifier lane status is reported

  Scenario: Two current missions are still an error
    Given the publication has 2 current missions
    When an editor checks "This game-changing release." in section "engineering"
    Then the check fails with "expected exactly one current record, found 2"
