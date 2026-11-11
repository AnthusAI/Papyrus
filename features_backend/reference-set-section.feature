Feature: An editor, or an agent in their session, changes only the section of an accepted Reference
  A Reference's section (a Newsroom section such as Security) decides where it sits on the site, for example which group on the videos page
  holds a video. Before this, tagging an accepted Reference meant approving it again and repeating its acceptance note to keep it, which also
  made a new vote. `papyrus references set-section` and the MCP tool `reference_set_section` change only the section and record who changed it
  and when. The acceptance, its note, the feedback and the star rating stay exactly as they were, so there is no new vote for the Cyclotron to
  learn from. A section can be named by display name, slug or the qualified form `machines-on-machines#security`; a name the site does not have
  is an error that says which forms are accepted and which sections exist. The command and the tool share one definition, so they give the same
  answer. Nothing here touches a real site or AWS: the commands run against an in-memory data client, and the site's function runs in a test.

  Scenario: Setting the section by slug changes only the section
    Given an accepted Reference with a note, a four star rating and no section
    When the editor sets its section to "security"
    Then the Reference is in the section "machines-on-machines#security"
    And its acceptance, note, feedback and rating are identical to before

  Scenario: A display name and the qualified form name the same section
    Given an accepted Reference with a note, a four star rating and no section
    When the editor sets its section by the name "Research Papers" and then by "machines-on-machines#security"
    Then the Reference is in the section "machines-on-machines#security"
    And its acceptance, note, feedback and rating are identical to before

  Scenario: A section the site does not have is a clear error that lists what is accepted
    Given an accepted Reference with a note, a four star rating and no section
    When the editor sets its section to "sports"
    Then the command is refused and nothing is written
    And the message lists the accepted forms and the enabled sections
    And a disabled section and a malformed qualified form are refused the same way

  Scenario: Clearing removes the section and nothing else
    Given an accepted Reference with a note, a four star rating and the section "machines-on-machines#security"
    When the editor clears its section
    Then the Reference has no section
    And its acceptance, note, feedback and rating are identical to before

  Scenario: A dry run reports the change and writes nothing
    Given an accepted Reference with a note, a four star rating and no section
    When the editor sets its section to "security" with a dry run
    Then the output says nothing was sent and names the section it would set
    And no section change is sent

  Scenario: Only an accepted Reference can be put in a section
    Given a pending Reference
    When the editor sets its section to "security"
    Then the command is refused because the Reference is not accepted

  Scenario: The MCP tool gives the same answer as the command
    Given an accepted Reference with a note, a four star rating and no section
    When the same change is made once with the command and once with the MCP tool reference_set_section
    Then both give the same result and leave the same Reference

  Scenario: The site's function writes only the section and who and when, for editors and for operators
    When the site's function sets, repeats, rejects, clears and operator-sets a section
    Then it writes only the section, who changed it and when
    And the function leaves the acceptance, note, feedback and rating identical to before
    And a reader, an unknown section, a disabled section and a pending Reference are refused before any write
    And an operator on AWS credentials can do it and is recorded by role session
