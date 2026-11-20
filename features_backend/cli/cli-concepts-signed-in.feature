@backend @cli-concepts-signed-in
Feature: A signed-in editor manages concepts from the papyrus CLI, with no AWS login
  An editor who is signed in to a site with `papyrus login` can already read the site's concepts. This feature is about changing them: making a
  concept with the name they typed, correcting a name, adding an alias, accepting a description so the public page uses it, and saying in words how
  two concepts relate. An editor's token may read the concepts and write nothing in them directly, and that stays true: every change goes through
  one of the site's own routes, open to the editor and administrator groups only, which checks what may change and records where the decision was made.
  A person may make these decisions from the CLI, so the CLI is not refused. But the CLI is also where a script or an agent works inside an editor's own
  session, so a record that says "an editor accepted this" must not read as if the editor did it in the Newsroom. The site works out where from the
  sign-in client the token was issued to, which it signs and the caller cannot change, and writes that on the record: "cli", "newsroom", or "signed-in"
  when the site has not told its CLI apart. The Newsroom's half of each scenario runs the site's own code in `scripts/test-concept-management.ts`; the
  CLI's half runs the real commands against a stand-in for the site that records what they send. Nothing here reaches a real site, login or AWS.

  Background:
    Given the CLI is signed in to a site as an editor and has no AWS credentials
    And the site knows the concepts "containment" and "confinement problem"

  Scenario: A concept an editor makes from the CLI keeps the capital letters they typed
    When the editor adds the core concept "Information flow control" to a section, asking for it to be made
    Then the CLI asks the site to make a concept named "Information flow control"
    And the site keeps those capitals in the name and the lower-case words in the key
    And a name that is not the same words as the key is refused

  Scenario: A hashtag still reads with spaces, and a lower-case slug takes the name the editor gives
    When the editor adds the core concept "#fake-website-networks" to a section, asking for it to be made
    Then the CLI asks the site to make a concept named "fake website networks"
    When the editor adds the core concept "non-interference" with the name "Non-interference", asking for it to be made
    Then the CLI asks the site to make a concept named "Non-interference"

  Scenario: An editor corrects a concept's name and adds an alias, and the key does not move
    When the editor renames "editor_concept--containment" to "Containment" and adds the alias "the containment issue"
    Then the CLI sends the changes to the site's review route and writes no model
    And the site writes the new name and the alias and keeps the concept's key

  Scenario: A review can change only what a review is for
    When a review asks to change a concept's kind, key, status to something unknown, or to write free text or an email address, or to touch another model
    Then the site refuses the whole review and writes nothing

  Scenario: Only a person accepts a description, and the public page uses it from then on
    Given the concept "Containment" has a description a model wrote
    When the editor tries to accept it as an AI agent
    Then the CLI refuses: only a person accepts a description
    When the editor accepts it as a person
    Then the CLI sends one change that marks the description as accepted by that person and does not touch its words
    And the public wiki page for the concept uses the description instead of the factual line

  Scenario: A decision made from the CLI says so, whatever the command claims
    When the editor accepts a concept's description from the CLI
    Then the site stamps the acceptance as made through the CLI
    And a mark the call claims was made in the Newsroom is stamped as made through the CLI
    And an earlier mark the call did not change keeps the place it was made
    And the origin is the CLI only for a token issued to the CLI's client, and "signed-in" on a site that has not told its CLI apart

  Scenario: A concept's public page has a plain address and never one that holds a page by someone else
    When the wiki sync writes pages for the concepts editors invented
    Then the page for "Containment" is at "containment" and not "editor-concept-containment"
    And a page by someone else already at that address is left as it is and the sync says how to resolve it
    And an older page with the kind in its address is reported and not moved

  Scenario: Two concepts are linked with the words that say how they relate
    When the editor links "editor_concept--containment" to "editor_concept--confinement-problem" with the note "Two sides of one fence"
    Then the CLI asks the site for a related-to link between the two concepts with that note
    And the site writes one confirmed link whatever order the two are given in, with the note, who wrote it and that it came from the CLI
    And writing the pair again replaces the words and keeps who first wrote them
    And a link without words, to itself, to a rejected concept or to a concept that does not exist is refused

  Scenario: Every reader of an editor's explanation reads the link between concepts
    Given an editor linked two concepts with words, from the CLI
    Then a section's context pack lists the link and its words on both concepts
    And the internal knowledge query indexes the words
    And the knowledge snapshot has a confirmed relation between the two entities and not the words
    And the Cyclotron's link examples and suggestion cuts pass it by

  Scenario: A Reference is linked from the CLI to another Reference or to a concept
    When the editor links the Reference "ref-1" to the concept "boxing" with the note "The sibling problem"
    Then the CLI asks the site for a tagged-with link from the Reference to "confinement problem" with that note
    When the editor links the Reference "ref-1" to the Reference "ref-2" as "supports"
    Then the CLI asks the site for a supports link between the two References

  Scenario: A dry run and a request for help send nothing
    When the editor runs each new command with --dry-run and with --help
    Then the site has been sent nothing

  Scenario: The routes are for editors and administrators only, and the models stay read-only to them
    Then the new routes allow the editor and administrator groups and no other group, and the handler checks the groups again
    And the site's concept and relation models still allow an editor to read and nothing else
