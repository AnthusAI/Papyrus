Feature: The image operations have one door that runs them as the person who signed in
  The newsroom and MCP reach the image operations through two fields on the site's data API: imageRead for operations that only read and imageWrite for
  operations that write or spend. Only editors and admins may use them. The image-service function behind them takes who is asking from the identity
  the API verified and never from the request, runs the same operations the command line runs, and records the person's name on what it writes. A write
  can be repeated safely with its request id, and a caller that declares itself an agent can only be held to more rules, never fewer. This step runs
  nothing but the style profile operations, against a fake backend; no model, provider or AWS is called.

  Scenario: Only editors and admins may use the door
    Given a door onto a publication with a saved style profile
    When a signed-in reader reads the profile through the door
    Then the door answers that the caller is not authorised
    When an editor reads the profile through the door
    Then the door answers with the profile

  Scenario: Each operation is run through the door that matches what it does
    Given a door onto a publication with a saved style profile
    When an editor tries to save through the read door
    Then the door says to use imageWrite
    When an editor tries to read through the write door
    Then the door says to use imageRead

  Scenario: Whether the caller is an admin comes from their group, not from anything they send
    Given a door onto a publication with a saved style profile
    When an editor asks to drop the binding constraint through the write door
    Then the door answers that the caller is not authorised and nothing is stored
    When an admin asks to drop the binding constraint through the write door
    Then the profile behind the door is at version 2 with no constraints
    And the new version records the admin's name

  Scenario: A caller that declares itself an agent cannot change a binding constraint even with an admin's rights
    Given a door onto a publication with a saved style profile
    When an admin who declares themselves an agent asks to drop the binding constraint
    Then the door answers that a person is required and nothing is stored

  Scenario: A write repeated with the same request id gets the first answer
    Given a door onto a publication with a saved style profile
    When an editor saves a mood change twice with the same request id
    Then both answers name version 2 and only one new version was stored
    And the same change with a different request id is refused as stale

  Scenario: A section's own style is read from the site for the resolution
    Given a door onto a publication with a saved style profile
    And the section "security" avoids "padlocks" in its own style
    When an editor resolves a cover for a Story in the section "security" through the door
    Then the answer through the door avoids "padlocks"
