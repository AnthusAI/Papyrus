Feature: Draft starter image style profiles are kept as files for the owner to correct before anything is saved
  Three publications, Machines on Machines, Threat Intelligence and Shipped, each get a draft starting style profile written from their own design files. The
  drafts are files in this repository, not data: nothing is written to any backend until the owner has answered the open questions at the top of each file
  and a person saves the profile through the command line. Every draft is labelled as a draft, lists its open questions first, keeps its example-picture slots
  as names and notes (no pictures), and holds a profile that the same validator a real save uses accepts.

  Scenario: Every draft is labelled, asks its questions first and is a valid profile
    Given the draft starter profiles in the examples folder
    Then there is a draft for "machines-on-machines", "threat-intelligence" and "shipped"
    And each draft says it is a draft for Ryan to correct, lists at least three open questions before anything else, and is set to review pictures after the fact
    And the profile in each draft passes the profile validator
    And no draft has any example picture attached, only slots listed by name and note

  Scenario: The Machines on Machines draft has the six starter types and the rule against generated realism
    Given the draft starter profiles in the examples folder
    Then the "machines-on-machines" draft has the image types cover-diagram, inline-diagram, cover-photo, cover-illustration, inline-illustration and social-card
    And its diagram types are drawn with the figure tools and never generated, and its photograph type is stock only
    And its binding rule bans generated pictures that look like photographs and leaves stock photographs alone

  Scenario: A draft is saved only by an admin who is a person, and only when someone chooses to
    Given the draft starter profiles in the examples folder
    And an image publication "ours" with no style profile
    When an editor who is not an admin tries to save the "machines-on-machines" profile
    Then the save is refused as not authorised and nothing is stored
    When an admin saves the "machines-on-machines" profile
    Then the starter profile is saved as version 1
