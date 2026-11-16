@pod
Feature: papyrus pod init and papyrus pod id start a pod and mint permanent ids
  `papyrus pod init POD --id-base URL` turns a folder of notes into a level 1 pod: it writes context.jsonld, which names the id base, and the
  generated papyrus.context.jsonld. It changes no note. `papyrus pod id POD [N]` prints new ids, each the id base followed by a random identifier.
  An id is minted once, written into a note by its owner, and never changed. It is never made from a file name or a path, and nothing in a pod
  reads a site: both commands work on files, with no sign-in, and neither publishes anything.

  Scenario: Init starts a pod in a folder of notes without changing a note
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod init POD --id-base https://example.org/id/"
    Then the pod command exits with status 0
    And the pod has the files "context.jsonld" and "papyrus.context.jsonld"
    And every note is exactly as it was
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 1 (0 of 2 notes typed)"

  Scenario: Init creates the folder when there is none
    Given no pod folder yet
    When I run the pod command "papyrus pod init POD --id-base https://example.org/id/"
    Then the pod command exits with status 0
    And the pod has the files "context.jsonld" and "papyrus.context.jsonld"

  Scenario: The root context names the id base
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod init POD --id-base https://example.org/id/"
    Then the pod file "context.jsonld" names the id base "https://example.org/id/"

  Scenario Outline: An id base that cannot start ids is refused and nothing is written
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod init POD --id-base <base>"
    Then the pod command exits with status 2
    And the pod report says "Nothing was written"
    And the pod has neither "context.jsonld" nor "papyrus.context.jsonld"

    Examples:
      | base                      |
      | http://example.org/id/    |
      | https://example.org/id    |
      | example.org/id/           |
      | https://example.org/id/?a |

  Scenario: Init needs an id base
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod init POD"
    Then the pod command fails with the message "requires --id-base URL"

  Scenario: Init refuses a pod that is already level 1 and leaves it alone
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod init POD --id-base https://other.example.org/id/"
    Then the pod command exits with status 2
    And the pod report says "is already a level 1 pod"
    And the pod folder is exactly as it was

  Scenario: Id prints one new id under the id base
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod id POD"
    Then the pod command exits with status 0
    And the pod prints 1 ids, each starting with "https://example.org/id/"
    And the pod folder is exactly as it was

  Scenario: Id prints as many new ids as asked, all different
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod id POD 5"
    Then the pod prints 5 ids, each starting with "https://example.org/id/"
    And the printed ids are all different

  Scenario: A new id is accepted by the check
    Given a started pod
    When I run the pod command "papyrus pod id POD"
    And a note "fresh.md" is written with the printed id as an Article
    And I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 1 (1 of 1 notes typed)"

  Scenario: An id is not made from a file name
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      Words.
      """
    When I run the pod command "papyrus pod id POD 3"
    Then none of the printed ids contains "slow-water"

  Scenario: Id needs a level 1 pod
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod id POD"
    Then the pod command exits with status 2
    And the pod report says "run `papyrus pod init"

  Scenario Outline: Id takes a whole number of ids
    Given a started pod
    When I run the pod command "papyrus pod id POD <count>"
    Then the pod command fails with the message "takes a whole number of ids"

    Examples:
      | count |
      | 0     |
      | many  |
      | -2    |

  Scenario: Help lists the three commands and says they need no sign-in
    When I run the pod command "papyrus pod --help"
    Then the pod command exits with status 0
    And the pod report says "init"
    And the pod report says "check"
    When I run the pod command "papyrus pod check --help"
    Then the pod report says "no sign-in and no site"
    And the pod report says "read only"
