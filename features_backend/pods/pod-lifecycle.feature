@pod
Feature: Pod lifecycle keys carry a note's stage, rating and review claims
  A note in a pod can say where it is in its life with the same keys, and the same values, that the newsroom's content item uses: `stage`, `type`,
  `section`, `format`, `rating`, `reviewedBy`, `reviewedOn`, `reviewedHash`, `spikedReason` and `heldReason`. Kanbus stays the task board: a pod never
  reads issues, and changing a note's stage is an edit to the note, not a card move.

  `stage` is one of idea, assignment, reporting, copywriting, illustration, typesetting, published, held, spiked or retired. There is one switch, said
  once: a note with a `stage` is built into a site only at `published`; a note with no `stage` is built unless it says `draft: true`; and a note
  may not carry both, so `pod check` refuses it. (Building a site from a pod is a later change; this feature is what the check accepts and refuses.)

  `rating` is a whole number from 1 to 4. A 5 is refused: a pod never grants five stars, and the note is a five-star candidate that a person confirms
  in the newsroom.

  `reviewedBy`, `reviewedOn` and `reviewedHash` are three flat keys, and they are claims. `reviewedHash` is the hash of the body that was reviewed,
  written `sha256:` and 64 hex digits, taken over the text after the closing `---` with line ends read as plain newlines. `pod check` reports "review
  is stale" when the body no longer matches it, and says what the body hashes to now. A review stamp in a pod can be typed by anyone: it never
  satisfies a gate, a required step, publishRequiresRating or a five-star rule, and `pod check` says so in one plain line.

  Scenario Outline: Every stage the newsroom has is a stage in a pod
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: <stage>
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

    Examples:
      | stage        |
      | idea         |
      | assignment   |
      | reporting    |
      | copywriting  |
      | illustration |
      | typesetting  |
      | published    |
      | held         |
      | spiked       |
      | retired      |

  Scenario: A stage nobody has is refused, with the nearest stage
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: pubished
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'stage' is 'pubished'; a stage is one of idea, assignment, reporting, copywriting, illustration, typesetting, published, held, spiked, retired; did you mean 'published'?" for the note "story.md"

  Scenario: A stage is one word of text
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: [idea, published]
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'stage' takes one value, not a list" for the note "story.md"

  Scenario Outline: A note with a stage and a draft flag is refused, whatever the flag says
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: published
      draft: <draft>
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "carries both stage and draft" for the note "story.md"

    Examples:
      | draft |
      | true  |
      | false |

  Scenario: A draft with no stage is fine, and so is a stage with no draft flag
    Given a started pod with an Article "story.md" carrying these keys:
      """
      draft: true
      """
    And the pod file "staged.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0021
      type: papyrus:Article
      stage: copywriting
      ---
      Words.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

  Scenario: Type, section and format use the same keys as the newsroom's content item
    Given a started pod with an Article "story.md" carrying these keys:
      """
      section: "[[water]]"
      format: explainer
      """
    And the pod file "water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0022
      type: papyrus:Section
      ---
      The water desk.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario Outline: A rating from one to four is accepted
    Given a started pod with an Article "story.md" carrying these keys:
      """
      rating: <rating>
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

    Examples:
      | rating |
      | 1      |
      | 2      |
      | 3      |
      | 4      |

  Scenario: A pod never grants five stars
    Given a started pod with an Article "story.md" carrying these keys:
      """
      rating: 5
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'rating' is 5, which a pod never grants; this note is a five-star candidate, and a person confirms five stars in the newsroom. Use 4 here" for the note "story.md"

  Scenario Outline: A rating that is not a whole number from one to four is refused
    Given a started pod with an Article "story.md" carrying these keys:
      """
      rating: <rating>
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'rating' takes a whole number from 1 to 4" for the note "story.md"

    Examples:
      | rating |
      | 0      |
      | 6      |
      | -1     |
      | 3.5    |
      | three  |
      | true   |

  Scenario: Reasons for a hold or a spike are plain text
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: held
      heldReason: Waiting for the second source
      """
    And the pod file "spiked.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0023
      type: papyrus:Article
      stage: spiked
      spikedReason: A dull story
      ---
      Words.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: A reason that is not text is refused
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: held
      heldReason: 7
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'heldReason' takes text" for the note "story.md"

  Scenario: A review whose hash matches the body is not stale
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: published
      reviewedBy: Ada Example
      reviewedOn: 2026-11-14
      """
    And the pod note "story.md" is stamped with the hash of its body
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

  Scenario: A review is stale once the body changes, and the report says what the body hashes to now
    Given a started pod with an Article "story.md" carrying these keys:
      """
      stage: published
      reviewedBy: Ada Example
      reviewedOn: 2026-11-14
      """
    And the pod note "story.md" is stamped with the hash of its body
    And the pod file "story.md" has "Words." replaced by "Other words."
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "review is stale: the body no longer matches reviewedHash; it now hashes to " for the note "story.md"
    And the pod report gives the current hash of the body of "story.md"

  Scenario: A line ending change alone does not make a review stale
    Given a started pod with an Article "story.md" carrying these keys:
      """
      reviewedBy: Ada Example
      reviewedOn: 2026-11-14
      """
    And the pod note "story.md" is stamped with the hash of its body
    And the pod note "story.md" is rewritten with Windows line endings
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario Outline: A hash that is not a hash is refused
    Given a started pod with an Article "story.md" carrying these keys:
      """
      reviewedBy: Ada Example
      reviewedOn: 2026-11-14
      reviewedHash: <hash>
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'reviewedHash' is sha256: and 64 hex digits" for the note "story.md"

    Examples:
      | hash                |
      | abc123              |
      | sha256:abc123       |
      | md5:0123456789abcdef0123456789abcdef |

  Scenario: A review stamp with no hash cannot be checked and is reported
    Given a started pod with an Article "story.md" carrying these keys:
      """
      reviewedBy: Ada Example
      reviewedOn: 2026-11-14
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has reviewedBy or reviewedOn and no reviewedHash, so the review cannot be checked against the body" for the note "story.md"

  Scenario: The day a review was claimed is a day
    Given a started pod with an Article "story.md" carrying these keys:
      """
      reviewedOn: yesterday
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'reviewedOn' takes a day written 2026-11-13" for the note "story.md"

  Scenario: A pod says in one plain line that its review keys are claims
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "review: review keys in a pod are claims, not newsroom review; nothing in a pod satisfies a gate, a required step, publishRequiresRating or a five-star rule"
    And the pod report says that line once

  Scenario: A pile of plain notes has no review line
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod check POD"
    Then the pod report does not say "review keys in a pod are claims"

  Scenario: The fixture pod carries every lifecycle key and passes
    Given a copy of the fixture pod
    Then the pod note "articles/slow-water.md" carries the keys "stage", "rating", "reviewedBy", "reviewedOn" and "reviewedHash"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: Lifecycle keys on an untyped note are the note's own
    Given a started pod with an Article "story.md" carrying these keys:
      """
      draft: true
      """
    And the pod file "scratch.md" has this text:
      """
      ---
      stage: whatever I like
      rating: 9
      ---
      A working note.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
