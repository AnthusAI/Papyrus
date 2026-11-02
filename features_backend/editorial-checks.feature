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

  Scenario: Add a policy pack with a classifier question from the command line
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    When an operator adds the pack with papyrus editorial policies add
    Then the policy command wrote 2 policies
    And policy "plain-claims" is stored as version 1 with source "operator-cli:fixture-judgment:ryan"
    And policy "plain-claims" keeps its classifier question, "yes" violation, threshold 0.7, review threshold 0.4 and message

  Scenario: Adding the same pack again changes nothing
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    When an operator adds the pack with papyrus editorial policies add
    And an operator adds the pack with papyrus editorial policies add
    Then the policy command wrote 0 policies
    And the plan says "unchanged\tplain-claims"

  Scenario: Changed content creates the next version of only that policy
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    When an operator adds the pack with papyrus editorial policies add
    And the pack's threshold is changed to 0.9
    And an operator adds the pack with papyrus editorial policies add
    Then the policy command wrote 1 policies
    And policy "plain-claims" is now version 2
    And policy "no-hype" is now version 1

  Scenario: A dry run prints the plan and writes nothing
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    When an operator dry-runs adding the pack
    Then the policy command wrote 0 policies
    And the plan says "would create\tplain-claims"

  Scenario: An invalid pack is refused before anything is written
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    And the pack's threshold is 7
    When an operator adds the pack with papyrus editorial policies add
    Then the policy command is refused with "not a valid policy-pack-v1 document"

  Scenario: A pack for another publication is refused
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    When an operator adds the pack for publication "elsewhere"
    Then the policy command is refused with "not elsewhere"

  Scenario: Exported policies load back unchanged
    Given a site with no editorial policies
    And a policy-pack file with a classifier question
    When an operator adds the pack with papyrus editorial policies add
    And an operator exports the policies and the site loses them and adds the export
    Then the site has the same detectors as before

  Scenario: Check a draft from the command line against a policy-pack file
    Given a policy-pack file whose policy "no-hype" flags "game-changing"
    When an operator runs papyrus editorial check on a draft saying "This is game-changing."
    Then the printed check result has a "no-hype" finding on "game-changing"

  # An operator reads the findings themselves, not just a count, so they can act on each one.
  Scenario: Checking a version from the command line prints every finding
    Given a stored check of version 1 with a violation of "no-hype" on "game-changing" and a judgment for review of "measured-or-model" on "Sales doubled."
    When an operator runs papyrus editorial check-version on version 1
    Then the printed summary says "1 violations" and "1 for review"
    And each finding is printed with its policy, severity, probability, message, excerpt and id
    And the violation is printed before the finding for review

  Scenario: Checking a version from the command line as JSON prints the full findings
    Given a stored check of version 1 with a violation of "no-hype" on "game-changing" and a judgment for review of "measured-or-model" on "Sales doubled."
    When an operator runs papyrus editorial check-version on version 1 with --json
    Then the printed JSON lists both findings with their ids, probabilities and excerpts

  # A judgment about the whole story has no passage to quote, so it says so instead of showing an empty excerpt.
  Scenario: A judgment about the whole story says it applies to the whole story
    Given Humanus returns a judgment finding for the whole story and one for the sentence "Sales doubled."
    When an editor checks "Sales doubled. Costs fell." in section "engineering"
    Then the whole-story finding's message starts with "Applies to the whole story"
    And the sentence finding keeps its excerpt "Sales doubled." and its message unchanged

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

  # PPY-2c4b56: items store a section name or slug; with no matching NewsroomSection the check still returns a result.
  Scenario: No section record: the check still runs and records the skip
    Given the section has no NewsroomSection record
    When an editor checks "This game-changing release." in section "engineering"
    Then the findings are for policies "no-hype"
    And the section is recorded as skipped because there is "no section configuration"

  Scenario: The section skip is stored with the checked version
    Given the section has no NewsroomSection record
    When the saved version of a story with "This game-changing release." is checked
    Then the stored check run records the section lane as skipped

  Scenario: One current mission: judgment checks run as before
    Given the publication has one current mission
    And the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then Humanus was asked to run the classifier with a 12 second deadline
    And the classifier lane status is reported

  # Editors never lose their rule checks to odd doctrine: two current missions cannot say which one governs, so no mission applies.
  Scenario: Two current missions: rule checks run, judgment checks are skipped
    Given the publication has 2 current missions
    And the editorial check settings turn the classifier on with a 12 second deadline
    When an editor checks "This game-changing release." in section "engineering"
    Then the findings are for policies "no-hype"
    And Humanus was asked to run without the classifier
    And the classifier lane is skipped because the publication has no mission

  # Production saw "NewsroomSection not found" for values like "Papyrus" or "articles": an unknown section checks against
  # the publication's policies with no section guidance.
  Scenario: A section name no section matches still gets the publication's policies
    Given the section has no NewsroomSection record
    When an editor checks "This game-changing synergy ships." in section "Newsroom How-To"
    Then the findings are for policies "no-hype"
    And the section is recorded as skipped because there is "no section configuration"

  # The severity names are info, warn and error; an info finding is a normal finding, not a crash.
  Scenario: An info finding is returned and stored with the checked version
    When the saved version of a story with "This synergy ships." is checked
    Then version 1 has a stored finding for policy "jargon" with severity "info"

  # Every saved version is checked on the server, so findings exist for content changed outside the editor (PPY: auto-run).
  Scenario: Saving a version checks it and stores the result with the version
    When version 1 of the story is saved with "This game-changing release." and checked
    Then Humanus was asked to check
    And version 1 has a stored check with 1 finding for policy "no-hype"

  # Identical content is never sent to the provider twice, which keeps automatic checks from running up a bill.
  Scenario: Checking a version again without changes does not ask Humanus again
    Given version 1 of the story is saved with "This game-changing release." and checked
    When version 1 of the story is checked again
    Then the check was skipped as unchanged
    And Humanus was not asked again

  Scenario: A new version with the same content reuses the earlier check
    Given version 1 of the story is saved with "This game-changing release." and checked
    When version 2 of the story is saved with the same content as version 1 and checked
    Then the check was skipped as unchanged
    And Humanus was not asked again
    And version 2 has a stored check with 1 finding for policy "no-hype"

  Scenario: Changed content is checked again
    Given version 1 of the story is saved with "This game-changing release." and checked
    When version 2 of the story is saved with "A calm release." and checked
    Then Humanus was asked to check
    And version 2 has a stored check with 0 finding for policy "no-hype"

  Scenario: The same text in another section is checked again, because the section picks the policies
    Given version 1 of the story is saved with "This synergy ships." and checked
    When version 2 of the story is saved in section "culture" with "This synergy ships." and checked
    Then Humanus was asked to check

  Scenario: A check whose judgment lane did not finish is retried on the next update
    Given version 1 of the story is saved with "This game-changing release." and checked
    And the stored check of version 1 did not finish its judgment lane
    When version 1 of the story is checked again
    Then Humanus was asked to check

  # A closing section pasted into several articles goes stale in all of them at once (seven Anth.us articles did).
  # The check compares a story with the latest version of the site's other stories; it never calls a model.
  Scenario: A closing paragraph copied across stories is flagged, naming the other story
    Given the site has a current story "other-article" that ends with the standard closing
    When the saved version of the story "this-article" ends with the standard closing and is checked
    Then the story "this-article" has a stored "cross-story-boilerplate" finding naming "other-article"

  Scenario: A story's own earlier version does not count
    Given the site has a superseded version of the story "other-article" that ends with the standard closing
    When version 2 of the story "this-article" is saved with its own earlier closing and checked
    Then the story "this-article" has no stored "cross-story-boilerplate" finding

  Scenario: A passage the other story only quotes is not boilerplate
    Given the site has a current story "other-article" that says "As the memo put it, \"we run this for clients at scale and we keep the source open so every client owns the whole thing\" and that is all."
    When the saved version of the story "this-article" with "We run this for clients at scale and we keep the source open so every client owns the whole thing." is checked
    Then the story "this-article" has no stored "cross-story-boilerplate" finding

  Scenario: A passage this story quotes is not boilerplate either
    Given the site has a current story "other-article" that says "We run this for clients at scale and we keep the source open so every client owns the whole thing."
    When the saved version of the story "this-article" with "She said \"we run this for clients at scale and we keep the source open so every client owns the whole thing\" twice." is checked
    Then the story "this-article" has no stored "cross-story-boilerplate" finding

  Scenario: Fewer shared words than the copy guard's run are not flagged
    Given the site has a current story "other-article" that says "We run this for clients at scale."
    When the saved version of the story "this-article" with "We run this for clients at scale." is checked
    Then the story "this-article" has no stored "cross-story-boilerplate" finding

  Scenario: The checks function may call everything its store calls
    The function talks to the site's data API with its own role, so a query its store
    makes without a grant fails at run time with 401, after deploy, for every editor.
    That happened when reusing an earlier check run was added without its grant.
    When the editorial-checks store's GraphQL operations are compared with the function's role
    Then every field the store calls is granted to the role
