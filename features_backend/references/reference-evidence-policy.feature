Feature: Which References count as evidence
  A Reference is a source the newsroom has collected. Collecting a source says
  nothing about whether a Story may lean on it. An editor decides that by
  accepting or rejecting the Reference, and only an accepted Reference, in its
  current version, is evidence.

  The same decisions teach the relevance model what the publication covers. An
  accepted Reference is an example of what belongs. A rejected one is an example
  of what does not belong only when the editor said the subject was the problem.
  A duplicate or a dead link says nothing about the subject, so it teaches
  nothing.

  Scenario Outline: Only an accepted Reference in its current version is evidence
    Given a Reference in its "<version>" version that an editor has left "<status>"
    Then a Story <may or may not> cite that Reference as evidence

    Examples:
      | version    | status   | may or may not |
      | current    | accepted | may            |
      | current    | pending  | may not        |
      | current    | rejected | may not        |
      | current    | archived | may not        |
      | superseded | accepted | may not        |

  Scenario: A Reference that was never found is not evidence
    Given no Reference at all
    Then a Story may not cite that Reference as evidence

  Scenario Outline: Every decision an editor records is one of four statuses
    When an editor records the decision "<what the editor wrote>"
    Then the Reference is filed as "<status>"

    Examples:
      | what the editor wrote | status   |
      | accepted              | accepted |
      | Accept                | accepted |
      | ready                 | accepted |
      | trusted               | accepted |
      | rejected              | rejected |
      | Reject                | rejected |
      | discarded             | rejected |
      | archived              | archived |
      | Archive               | archived |
      | pending               | pending  |
      | maybe later           | pending  |

  Scenario: A Reference nobody has decided on is pending
    When an editor records no decision
    Then the Reference is filed as "pending"

  Scenario Outline: A rejection carries one of seven reasons
    When an editor gives the rejection reason "<what the editor wrote>"
    Then the rejection reason is kept as "<reason>"

    Examples:
      | what the editor wrote | reason           |
      | out_of_scope          | out_of_scope     |
      | Out of scope          | out_of_scope     |
      | policy-exclusion      | policy_exclusion |
      | duplicate             | duplicate        |
      | low quality           | low_quality      |
      | unavailable           | unavailable      |
      | provenance            | provenance       |
      | other                 | other            |

  Scenario: A reason outside the seven is refused
    When an editor gives the rejection reason "boring"
    Then the rejection reason is refused as unsupported

  Scenario Outline: What a decision teaches the relevance model
    Given an editor left the "<version>" version of a Reference "<status>" and gave the reason "<reason>"
    Then the relevance model learns "<lesson>" from that Reference

    Examples:
      | version    | status   | reason           | lesson   |
      | current    | accepted | none             | positive |
      | current    | rejected | out_of_scope     | negative |
      | current    | rejected | policy_exclusion | negative |
      | current    | rejected | duplicate        | nothing  |
      | current    | rejected | low_quality      | nothing  |
      | current    | rejected | unavailable      | nothing  |
      | current    | rejected | provenance       | nothing  |
      | current    | rejected | none             | nothing  |
      | current    | pending  | none             | nothing  |
      | current    | archived | none             | nothing  |
      | superseded | accepted | none             | nothing  |

  Scenario: The reason on the latest vote wins over one kept in older metadata
    Given a rejected Reference whose latest vote says "out_of_scope" and whose metadata says "duplicate"
    Then the relevance model learns "negative" from that Reference

  Scenario: A reason kept only in metadata is still read
    Given a rejected Reference with no vote reason whose metadata says "policy_exclusion"
    Then the relevance model learns "negative" from that Reference
