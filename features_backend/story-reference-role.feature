@backend @story-reference-role
Feature: A signed-in editor marks a Story's consulted source as cited
  While reporting, an editor attaches the sources they read to a Story as "consulted". Once the draft quotes one, they mark it "cited" and give
  it the citation key the draft uses, from the newsroom or with `papyrus stories link-reference --role cited --citation-key <key>` in a session
  opened with `papyrus login`. The link between a Story and a source is a SemanticRelation, and the editor and administrator groups may read and
  create SemanticRelations but never update one: category notes, provenance and reference links stay append-only for a browser or a signed-in
  CLI. Changing a role is an update, so when the site refuses a signed-in editor's direct update (a certain refusal: nothing was written) the
  CLI makes the change through the site's own route, `setStoryReferenceRole`, which is open to
  editors and administrators only, refuses any relation that is not a Story's source, and writes nothing but the role, the citation key, the
  note, who changed it (from the sign-in, not from the command) and where. An operator with AWS credentials keeps writing the row directly.
  The CLI runs for real against a stand-in for the site that enforces those rules; the route's half runs the site's own code
  (amplify/functions/category-action/story-reference-role.ts). Nothing here reaches a real site, login or AWS.

  Background:
    Given a Story with one saved version and one Reference it was reported from
    And the Reference is attached to the Story as consulted by "Ada Example"

  Scenario: An editor marks a consulted source as cited with its citation key
    When a signed-in editor "Grace Editor" runs "papyrus stories link-reference --role cited --citation-key smith2026"
    Then the command succeeds and prints that the link was updated
    And the source is cited with the citation key "smith2026"
    And the change is recorded as made by "Grace Editor" through the CLI, and "Ada Example" is still who attached it
    And the site refused the CLI's direct update before writing anything, and the route made the change
    And it is still one link between the Story and the source

  Scenario: An administrator may mark a source as cited too
    When a signed-in administrator "Ian Admin" runs "papyrus stories link-reference --role cited --citation-key smith2026"
    Then the command succeeds and prints that the link was updated
    And the source is cited with the citation key "smith2026"

  Scenario: A source the Story is based on is never weakened to cited
    Given the Reference is attached to the Story as based on
    When a signed-in editor "Grace Editor" runs "papyrus stories link-reference --role cited --citation-key smith2026"
    Then the command succeeds and prints that the link was updated
    And the source is still based on, with the citation key "smith2026"

  Scenario: An editor's token still cannot update any relation directly
    When a signed-in editor tries to rewrite the Story's source relation directly
    Then the site refuses with "Not Authorized to access updateSemanticRelation on type Mutation"
    And the source is still consulted

  Scenario: An editor cannot change any other relation through the route
    Given the site holds a category note relation and a reference link relation
    When a signed-in editor asks the route to mark each of them cited
    Then the site refuses each with "not a source attached to a Story"
    And neither relation changed

  Scenario: A viewer cannot change a source's role
    When a signed-in viewer "Val Viewer" runs "papyrus stories link-reference --role cited --citation-key smith2026"
    Then the command fails with "Not Authorized to access setStoryReferenceRole on type Mutation"
    And the command printed no write line
    And the source is still consulted

  Scenario: A signed-in person in no group cannot change a source's role
    When a signed-in person in no group "Nora Nobody" runs "papyrus stories link-reference --role cited --citation-key smith2026"
    Then the command fails with "Not Authorized to access setStoryReferenceRole on type Mutation"
    And the source is still consulted

  Scenario: An operator with AWS credentials keeps writing the row directly
    When an operator on the IAM lane runs "papyrus stories link-reference --role cited --citation-key smith2026 --author-label Ops"
    Then the command succeeds and prints that the link was updated
    And the source is cited with the citation key "smith2026"
    And the route was not called

  Scenario: A site whose backend predates the route says what to do instead
    Given the site's backend has not been deployed with the route yet
    When a signed-in editor "Grace Editor" runs "papyrus stories link-reference --role cited --citation-key smith2026"
    Then the command fails with "predates the setStoryReferenceRole route"
    And the failure names the operator's IAM lane as the way to do it today
    And the source is still consulted
