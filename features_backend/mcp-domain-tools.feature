Feature: Site tools preserve editorial and reader authority
  Editors and readers use structured site tools in their own authority. A stale card must not overwrite a newer decision.

  Scenario: An editor reads the current Story and its evidence
    Given an editor connected to a site with a Story and evidence
    When the editor asks for the Story and its evidence
    Then the tools return the current Story version and the evidence lineage

  Scenario: A site without conditional writes refuses a Reference decision
    Given an editor connected to a site with a Story and evidence
    When the editor decides a Reference without a conditional-write adapter
    Then the decision is refused without changing the Reference

  Scenario: A reader cannot use staff tools
    Given a reader connected to a site with a verified site subject
    When the reader asks for the Story
    Then the staff tool is refused

  Scenario: A reader submission uses the verified site subject
    Given a reader connected to a site with a verified site subject
    When the reader submits a link
    Then the site's reader policy receives the verified site subject

  Scenario: A Reference card identifies its current version and revision
    Given an editor connected to a site with a current Reference
    When the editor opens the Reference by its lineage
    Then the Reference card identifies the current version and revision

  Scenario: A tenant cannot read a Reference without an ownership key
    Given an editor connected to a shared site with a current Reference
    When the editor opens the Reference by its lineage
    Then the Reference read is refused

  Scenario: An agent accepts the Reference shown on a current card
    Given an editor connected to a site with a current Reference
    When the agent accepts the Reference shown on the card
    Then the site receives the current version and revision for an agent decision

  Scenario: An outdated Reference card cannot be accepted
    Given an editor connected to a site with a current Reference
    When the agent accepts an outdated Reference card
    Then the Reference decision is refused

  Scenario: A reader cannot give itself staff authority through tool arguments
    Given a reader connected to the private site-tools service
    When the reader includes an administrative role in a tool request
    Then the service refuses the forged role

  Scenario: Reader tools are unavailable when the site has no reader plugin
    Given a reader connected to the private site-tools service without a reader plugin
    When the reader lists the site's tools
    Then the reader sees no reader tools

  Scenario: A tenant cannot read another publication's assignment
    Given an editor connected to a shared site with an Assignment for another publication
    When the editor opens that Assignment
    Then the Assignment read is refused

  Scenario: A Story search returns a bounded page of matching Stories
    Given an editor connected to a site with a searchable Story
    When the editor searches for the Story with a page size of two
    Then the result contains the Story and a continuation token

  Scenario: An agent answers an open review with its own attribution
    Given an editor connected to a site with an open review
    When the agent answers the current review with feedback
    Then the saved answer names the agent and returns the updated revision

  Scenario: A review changed after it was opened
    Given an editor connected to a site with an open review
    When the agent answers an outdated review
    Then the review answer is refused as stale

  Scenario: A publish approval remains open for a person
    Given an editor connected to a site with a publish approval request
    When the agent tries to approve the publish request
    Then the request remains open for a person

  Scenario: A concurrent review answer wins the storage race
    Given an editor connected to a site with an open review
    And another answer wins before the agent's update
    When the agent answers the current review with feedback
    Then the review answer is refused as stale

  Scenario: An editor agent rates the Story shown on a current card
    Given an editor connected to a site with a rateable Story
    When the agent gives that Story four stars
    Then the Story card shows four stars and a new revision

  Scenario: A changed Story rating rejects an outdated card
    Given an editor connected to a site with a rateable Story
    When the agent rates the Story from an outdated card
    Then the Story rating is refused as stale

  Scenario: A reader cannot rate a Story through a staff tool
    Given a reader connected to a site with a verified site subject
    When the reader tries to rate a Story
    Then the staff tool is refused

  Scenario: A saved draft remains saved when its editorial check is unavailable
    Given an editor connected to a site with the agent draft operation
    When the agent saves a new draft and its check is unavailable
    Then the tool reports both the saved draft and the check status

  Scenario: A Story procedure does not mistake inaccessible assignments for missing work
    Given an editor connected to a site with a rateable Story
    When the editor asks for the next Story procedure steps
    Then the direction and research steps are reported as unknown

  Scenario: A publish request returns the person's approval state
    Given an editor connected to a site with a publish request operation
    When the agent requests publication for the current Story
    Then the tool reports a pending human approval request
