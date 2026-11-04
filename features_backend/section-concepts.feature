Feature: An editor lists the concepts a section should be especially aware of, and every agent in the section reads them
  Each section can have core concepts: the editor's own example is the confinement problem and the containment problem in a security section.
  The list is stored on the section as its core concepts, each with the editor's note, who added it and when. The command line lists
  the concepts, adds one by a name, an alias, a hashtag or a node key, makes a new editor concept only when asked, and removes one; it writes
  unless it is asked for a dry run. Every agent's context pack then carries one card for each core concept, with its aliases, kind,
  description, the editor's note and its links to other concepts, and a ring of the accepted References that are tagged with or mention a
  core concept. A concept that no longer resolves or was rejected is a warning, never a card. A site whose data API predates the field
  reads as having none. Nothing here calls a model or the network.

  Background:
    Given a newsroom whose section "law-policy" has one core concept and a Story "story-1" in it

  Scenario: The command lists what the section has as core concepts
    When the editor lists the core concepts of the section
    Then the list shows the concept "containment problem" as a core concept

  Scenario: A concept is added by name with the editor's note
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    When the editor adds the concept "confinement problem" with the note "The sibling of containment"
    Then the section has both core concepts in the order they were added
    And the new entry holds the note, who added it and when

  Scenario Outline: A concept can be named in any of its forms
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    When the editor adds the concept "<form>"
    Then the section has the core concept "confinement problem"

    Examples:
      | form                                   |
      | Confinement Problem                    |
      | boxing                                 |
      | #confinement-problem                   |
      | editor_concept--confinement-problem    |

  Scenario: An unknown name fails unless the editor asks for the concept to be made
    When the editor adds the concept "the sandbox problem"
    Then the command is refused saying "add --create"
    And the section still has one core concept
    When the editor adds the concept "the sandbox problem" asking to create it
    Then the section has the core concept "the sandbox problem"
    And the newsroom holds an editor concept written exactly as the shared fixture says

  Scenario: A rejected concept cannot be added
    Given the newsroom knows a rejected concept "confinement problem"
    When the editor adds the concept "confinement problem"
    Then the command is refused saying "was rejected"

  Scenario: A dry run changes nothing
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    When the editor adds the concept "confinement problem" as a dry run
    Then the section still has one core concept
    And the newsroom has written nothing

  Scenario: A concept is removed, even one that has since been rejected
    Given the newsroom knows a concept "confinement problem" with the alias "boxing"
    And the section has "confinement problem" as a core concept too
    When the editor removes the concept "boxing"
    Then the section still has one core concept
    When the concept "containment problem" is rejected
    And the editor removes the concept "containment problem"
    Then the section has no core concepts

  Scenario: Every profile reads one card for each core concept
    Given the core concept has an alias, a description and the editor's note "Why it matters here"
    And the concept is linked to another concept by a suggestion and by a link an editor accepted with the note "Two sides of one fence"
    When the context pack is built for each of the reporter, the copywriter and the editor on the Story
    Then each pack's section concepts layer holds a card for "containment problem"
    And the card shows the alias, the kind, the description and the editor's note
    And the card lists the accepted link with its note before the suggested one
    And the section concepts come before the section's published Stories in every pack

  Scenario: A core concept that is gone or rejected is a warning and not a card
    Given the section also has a core concept that no longer exists
    And the core concept "containment problem" is rejected
    When the reporter context pack is built for the Story
    Then the section concepts layer holds no card
    And the warnings name both concepts

  Scenario: Machine links give way first when the core is over budget
    Given the core concept has an alias, a description and the editor's note "Why it matters here"
    And the concept is linked to another concept by a suggestion and by a link an editor accepted with the note "Two sides of one fence"
    When the reporter context pack is built with room for the core layers minus one character
    Then the card still lists the accepted link with its note
    And the card no longer lists the suggested link
    And the section concepts layer records the dropped machine link

  Scenario: References tagged with or mentioning a core concept are a ring, best first
    Given an accepted Reference mentions the core concept and an editor-rated Reference is tagged with it
    When the reporter context pack is built for the Story
    Then the concept References layer lists the editor-rated one first, labelled "containment problem (tagged)"
    And the mention is labelled "containment problem (mentioned)"
    And a pending Reference tagged with the concept is not listed

  Scenario: The Story's own References are left out of the concept ring
    Given the Story's own Reference is tagged with the core concept
    When the reporter context pack is built for the Story
    Then the concept References layer does not list the Story's own Reference

  Scenario: A section with no core concepts says why
    Given the section has no core concepts
    When the reporter context pack is built for the Story
    Then both concept layers are empty with the reason "the section has no core concepts"

  Scenario: A site that predates the field is read without it
    Given a site whose schema has no core concepts on a section
    When the router reads that site's sections twice
    Then both reads return the sections and the field was asked for once

  Scenario: The command line and the hashtag box make the same concept
    Then the Python writer produces every editor concept in the shared fixture
