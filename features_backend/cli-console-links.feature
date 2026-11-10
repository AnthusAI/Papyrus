Feature: The CLI hands an editor the console link of the item it worked on
  An agent that works on a Story, Reference, Concept, Assignment or review item for an editor should end with a link
  that opens exactly that item in the newsroom console. One place builds those addresses, from the console address the
  signed-in site publishes (or one the person names), and the commands that already print an item print its link too.
  Building a link needs no network. Reading the site is only for turning a slug, a version number or a name into the id
  the console takes. A console address that is not known is an error that says so; it is never guessed. Nothing here
  touches a real site, browser or keychain.

  Background:
    Given the console is at "https://newsroom.news.example.test/newsroom"

  Scenario: A Story gets the editor page of one version, its board drawer and its checklist
    When the story addresses are built for lineage "item-story" and version "item-story-v2"
    Then the "story" link is "https://newsroom.news.example.test/newsroom/articles/item-story-v2"
    And the "story-board" link is "https://newsroom.news.example.test/newsroom/articles?open=contentItem%3Aitem-story"
    And the "checklist" link is the same as the "story-board" link
    And the checklist link is said to have no address of its own

  Scenario Outline: Each other kind of item has one address
    When the "<kind>" address is built for "<id>"
    Then the link is "<url>"

    Examples:
      | kind       | id                          | url                                                                                          |
      | reference  | reference-corpus-a-b        | https://newsroom.news.example.test/newsroom/references/reference-corpus-a-b                  |
      | concept    | semantic-node-voice-cloning | https://newsroom.news.example.test/newsroom/concepts?node=semantic-node-voice-cloning        |
      | assignment | assignment-123              | https://newsroom.news.example.test/newsroom/assignments/assignment-123                       |
      | review     | rr-0123abcd                 | https://newsroom.news.example.test/newsroom/needs-me/rr-0123abcd                             |

  Scenario: Ids are encoded so they cannot change the address
    When the "reference" address is built for "a/b?c#d"
    Then the link is "https://newsroom.news.example.test/newsroom/references/a%2Fb%3Fc%23d"

  Scenario: A console mounted at the root of its host has no newsroom path
    Given the console is at "https://newsroom.example.test/"
    When the "assignment" address is built for "assignment-123"
    Then the link is "https://newsroom.example.test/assignments/assignment-123"

  Scenario: Building an address makes no network call
    When the story addresses are built for lineage "item-story" and version "item-story-v2"
    Then no site was read and no network call was made

  Scenario: An unknown console address fails clearly and builds nothing
    Given the person is signed in to a site that publishes no console address
    And no console address is given
    When the person runs the links command "papyrus links --review rr-1"
    Then the command fails saying the console address is unknown and how to give it
    And no link is printed

  Scenario: The flag beats the environment, which beats what the site publishes
    Given the signed-in site publishes the console address "https://newsroom.site.example.test/newsroom"
    And the environment names the console address "https://env.example.test/newsroom"
    When the person runs the links command "papyrus links --review rr-1 --console-url https://flag.example.test"
    Then the link printed is "https://flag.example.test/needs-me/rr-1"
    When the person runs the links command "papyrus links --review rr-1"
    Then the link printed is "https://env.example.test/newsroom/needs-me/rr-1"

  Scenario: The signed-in site's published console address is used
    Given the signed-in site publishes the console address "https://newsroom.site.example.test/newsroom"
    And no console address is given
    When the person runs the links command "papyrus links --review rr-1"
    Then the link printed is "https://newsroom.site.example.test/newsroom/needs-me/rr-1"

  Scenario Outline: A console address that is not a plain https address is refused
    When the person runs the links command "papyrus links --review rr-1 --console-url <address>"
    Then the command fails saying it is not a console address

    Examples:
      | address                              |
      | http://newsroom.example.test         |
      | https://user@newsroom.example.test   |
      | https://newsroom.example.test/?x=1   |
      | newsroom.example.test                |

  Scenario: A site file's console address that is not https is ignored
    Then the site file value "http://newsroom.example.test" is left out
    And the site file value "https://newsroom.example.test/newsroom/" is kept as "https://newsroom.example.test/newsroom"

  Scenario: A story is found by slug and linked to its current version
    Given the site has the story "item-story" with the slug "my-story" at versions 1 and 2, version 2 current
    When the person runs the links command "papyrus links --story my-story"
    Then the "story" link is "https://newsroom.news.example.test/newsroom/articles/item-story-v2"
    And the "story-board" link is "https://newsroom.news.example.test/newsroom/articles?open=contentItem%3Aitem-story"

  Scenario: A story version is chosen by number or by id
    Given the site has the story "item-story" with the slug "my-story" at versions 1 and 2, version 2 current
    When the person runs the links command "papyrus links --story item-story --version 1"
    Then the "story" link is "https://newsroom.news.example.test/newsroom/articles/item-story"
    When the person runs the links command "papyrus links --story item-story --version item-story-v2"
    Then the "story" link is "https://newsroom.news.example.test/newsroom/articles/item-story-v2"

  Scenario: A version that does not exist is an error, not a dead link
    Given the site has the story "item-story" with the slug "my-story" at versions 1 and 2, version 2 current
    When the person runs the links command "papyrus links --story item-story --version 9"
    Then the command fails saying the story has no version 9
    And no link is printed

  Scenario: A story that does not exist is an error, not a dead link
    Given the site has the story "item-story" with the slug "my-story" at versions 1 and 2, version 2 current
    When the person runs the links command "papyrus links --story nothing-here"
    Then the command fails saying no story was found
    And no link is printed

  Scenario: A Reference, a Concept and an Assignment are checked against the site first
    Given the site has the Reference "reference-a-v1" in lineage "reference-a"
    And the site has the concept "Voice cloning" with the node key "concept--voice-cloning" and the lineage "semantic-node-voice-cloning"
    And the site has the Assignment "assignment-1"
    When the person runs the links command "papyrus links --reference reference-a-v1 --concept concept--voice-cloning --assignment assignment-1"
    Then the link printed is "https://newsroom.news.example.test/newsroom/references/reference-a"
    And the link printed is "https://newsroom.news.example.test/newsroom/concepts?node=semantic-node-voice-cloning"
    And the link printed is "https://newsroom.news.example.test/newsroom/assignments/assignment-1"

  Scenario: Naming nothing is an error that shows the usage
    When the person runs the links command "papyrus links"
    Then the command fails saying at least one item must be named

  Scenario: The links can be printed as JSON
    When the person runs the links command "papyrus links --review rr-1 --json"
    Then the JSON names the console and one "review" link with its address

  Scenario Outline: The commands that print an item also print its console link
    When the person runs the "<command>" command
    Then a "console" row for the "story" link ends with "<ending>"

    Examples:
      | command      | ending                                           |
      | stories create | /newsroom/articles/item-created-v1             |
      | stories save-version | /newsroom/articles/item-story-v3         |
      | stories show | /newsroom/articles/item-story-v2                 |

  Scenario: references show prints the Reference's console link
    When the person runs the "references show" command
    Then the output has the line "console: https://newsroom.news.example.test/newsroom/references/reference-a"

  Scenario: A command's own result is kept when the console address is unknown
    Given the person is signed in to a site that publishes no console address
    And no console address is given
    When the person runs the "stories show" command
    Then the output has a "console" row saying it is unavailable
    And the command succeeded

  Scenario: A draft save names the exact version, never only the lineage
    When the person runs the "stories save-version" command
    Then the "story" console row is the editor page of the version just saved
    And the "story" console row has no "open=" drawer query
    And a "console" row for the "story-board" link ends with "/newsroom/articles?open=contentItem%3Aitem-story"

  Scenario: The draft and copy-edit steps tell the agent to share a review link
    Then the "draft" step note says to share a review link with the exact version
    And the "copy_edit" step note says to share a review link
    And the template version and the step keys are unchanged

  Scenario: The agent guide makes the link a required step of story work
    Then the guide task "write-story" has a required section "Show the editor the console link" that names the exact version and the unavailable case
