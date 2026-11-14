Feature: A signed-in person reads a site's References, Stories and Assignments with the site's own corpus and ids
  An editor or a reporting agent signed in to a newsroom runs read commands from any directory. Every id a command prints is an id the
  next command accepts: the lineage id that `stories show` prints finds the Reference, and so does the record id that `references list`
  prints. A corpus key is the publication's key; the record id `knowledge-corpus-<key>` means the same corpus. A corpus that does not
  exist is an error that names the corpus the site serves, never an empty table. A catalog registers into the site's own corpus when
  `--corpus-key` names it, even though the steering file shipped with the tool lists other corpora. A person can read one Assignment and
  list the Stories, and can name a section by its name or its id.

  Scenario: A Reference is found by the lineage id that stories show prints
    Given the signed-in site has the Reference "ref-1" in the corpus "ai-ml-research"
    When a signed-in person shows the Reference "ref-1"
    Then the shown Reference has the record id "ref-1-v1" and the lineage id "ref-1"

  Scenario: references show and references text take the lineage id after --reference, and fail loudly without an id
    Given the signed-in site has the Reference "ref-1" in the corpus "ai-ml-research"
    When a signed-in person runs references show with "--reference ref-1"
    Then the command prints the Reference with the record id "ref-1-v1"
    When a signed-in person runs references show with no arguments
    Then the command fails with exit code 2 saying "requires a Reference id"
    When a signed-in person runs references text with "--reference ref-1 --offest 5"
    Then the command fails with exit code 2 saying "does not take --offest"

  Scenario: A Reference is found by the record id that references list prints
    Given the signed-in site has the Reference "ref-1" in the corpus "ai-ml-research"
    When a signed-in person shows the Reference "ref-1-v1"
    Then the shown Reference has the record id "ref-1-v1" and the lineage id "ref-1"

  Scenario: A corpus key on references show is honoured
    Given the signed-in site has the Reference "ref-1" in the corpus "ai-ml-research"
    When a signed-in person asks for the Reference "ref-1" in the corpus "threat-intelligence"
    Then the command fails saying the Reference is in the corpus "ai-ml-research", not "threat-intelligence"

  Scenario: A Reference that does not exist is an error
    Given the signed-in site has the Reference "ref-1" in the corpus "ai-ml-research"
    When a signed-in person shows the Reference "nope"
    Then the command fails saying the Reference was not found

  Scenario: A corpus that does not exist is an error, not an empty table
    Given the signed-in site serves the corpus "ai-ml-research" with no References
    When a signed-in person lists the References of the corpus "nonsense"
    Then the command fails saying the corpus is unknown and the site serves "ai-ml-research"

  Scenario: A corpus that exists and has no References is an empty table
    Given the signed-in site serves the corpus "ai-ml-research" with no References
    When a signed-in person lists the References of the corpus "ai-ml-research"
    Then the list is empty and the command succeeds

  Scenario: The record id of a corpus names the same corpus as its key
    Then the corpus key "knowledge-corpus-ai-ml-research" means the corpus "ai-ml-research"

  Scenario: A catalog registers into the site's corpus although the shipped steering file does not list it
    Given the signed-in site serves the corpus "ai-ml-research" with no References
    And the shipped steering file lists only the corpus "threat-intelligence"
    When a catalog is registered with the corpus key "ai-ml-research"
    Then the catalog registers into the corpus "ai-ml-research"

  Scenario: A catalog corpus key that is neither listed nor the site's corpus is refused
    Given the signed-in site serves the corpus "ai-ml-research" with no References
    And the shipped steering file lists only the corpus "threat-intelligence"
    When a catalog is registered with the corpus key "nonsense"
    Then the command fails saying the site's corpus is "ai-ml-research"

  Scenario: The steering file in the Papyrus source tree is not a site's choice
    Given a checkout of the Papyrus source tree that holds a steering file
    Then the steering file is not treated as chosen by a site
    And a checkout of a site that holds a steering file does treat it as chosen

  Scenario: Stories are listed by lineage id, newest first
    Given the signed-in site has the Stories "a" (idea), "b" (reporting) and "c" (spiked)
    When a signed-in person lists the Stories
    Then the Stories listed in order are "b" and "a"

  Scenario: Stories are listed for one stage and one section named by its name
    Given the signed-in site has the Stories "a" (idea), "b" (reporting) and "c" (spiked)
    When a signed-in person lists the Stories at the stage "idea" in the section "News Desk"
    Then the only Story listed is "a"

  Scenario: An Assignment is read with its events
    Given the signed-in site has the Assignment "as-1" held by "someone" with one event
    When a signed-in person shows the Assignment "as-1"
    Then the output gives the status, the Story, who holds it and the event

  Scenario: A missing Assignment is an error
    When a signed-in person shows the Assignment "x"
    Then the command fails saying the Assignment was not found

  Scenario: A Story can be created in a section named by its name
    Given the signed-in site has the section "news" titled "News Desk"
    When a Story is created in the section "News Desk"
    Then the Story is stored in the section "news"

  Scenario: A publish with no amplify_outputs.json asks the newsroom to project the page
    Given a signed-in person has no amplify_outputs.json for the chosen site
    Then the publish asks the newsroom to project the page

  Scenario: An amplify_outputs.json of another site never decides for the chosen site
    Given a signed-in person has the amplify_outputs.json of a different site
    Then that file is not used and the publish asks the newsroom to project the page
