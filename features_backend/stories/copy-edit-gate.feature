@backend @editorial-checks
Feature: The copy-edit gate fixes only what is mechanical
  After copywriting saves a version, the copy-edit step applies the replacements that the site's own policies declare
  (a stale name that a phrase policy replaces, an uncontracted form where the house voice wants contractions) as a new
  version by AI. Everything else stays a finding and gets rewrite options stored with the check result. A version that
  still has an error-severity violation is held for a person instead of advancing. The copy-edit step never publishes.

  Background:
    Given a newsroom with a story drafted as "We do not use Plexus. This is a game-changing release."
    And the site policies are:
      | key        | phrase          | replacement | severity |
      | stale-name | Plexus          | Primus      | error    |
      | no-hype    | game-changing   |             | error    |
      | vague      | release         |             | warn     |

  Scenario: Mechanical fixes become a new version by AI and the rest keep their findings
    When the copy-edit step runs on the story
    Then a new version 2 exists by "AI" with the reason "copy edit: 1 mechanical fix (stale-name)"
    And version 2 reads "We do not use Primus. This is a game-changing release."
    And the first version still reads "We do not use Plexus. This is a game-changing release."
    And the check of version 2 lists the finding for "no-hype" with 2 rewrite options
    And the check of version 2 does not list a finding for "stale-name"

  Scenario: A surviving error finding holds the story and raises a review request
    When the copy-edit step runs on the story and raises review requests
    Then the result holds the story because of "no-hype"
    And one open flag review request about the story names version 2

  Scenario: An uncontracted form is mechanical only where a policy asks for contractions
    Given the site has a policy "contractions" that wants contractions
    When the copy-edit step runs on the story
    Then version 2 reads "We don't use Primus. This is a game-changing release."

  Scenario: Without such a policy an uncontracted form is left alone
    When the copy-edit step runs on the story
    Then version 2 reads "We do not use Primus. This is a game-changing release."

  Scenario: A clean version is not held and not changed
    Given the story is redrafted as "We do not use Primus."
    When the copy-edit step runs on the story
    Then the story has only version 1
    And the result does not hold the story

  Scenario: Running again on the same text calls no model and changes nothing
    When the copy-edit step runs on the story
    And the copy-edit step runs on the story again
    Then the second run is skipped as already copy-edited
    And the story has exactly 2 versions

  Scenario: A dry run lists the mechanical fixes and writes nothing
    When the copy-edit step previews the story
    Then the preview lists a fix from "Plexus" to "Primus"
    And the story has only version 1

  Scenario: Missing provider keys are reported once and the fixes still land
    Given rewrite options cannot be produced because no provider key is configured
    When the copy-edit step runs on the story
    Then version 2 reads "We do not use Primus. This is a game-changing release."
    And the result says rewrite options are unavailable

  Scenario: The copy-edit step never publishes or moves the stage
    When the copy-edit step runs on the story
    Then version 2 has the stage of version 1 and is not published
