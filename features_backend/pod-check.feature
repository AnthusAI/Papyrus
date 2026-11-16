@pod
Feature: papyrus pod check reports a pod's level and every problem
  A pod is a folder of Markdown notes. Any folder of notes is a pod at level 0: nothing is required of it, and an untyped note is never wrong.
  A pod at level 1 has a context.jsonld at its root and front matter on the notes its owner chooses: a permanent id, a type, facts and typed links.
  That is a pinned, stricter profile of Vault-LD 0.5.0, and `papyrus pod check` is its conformance authority.

  The check only reads. It never writes a file, never mints or repairs an id, never signs in and never contacts a site. It reports the level and
  every problem it finds, each naming the note and what to do, and exits with status 1 when there is any problem. A pod with no site is private;
  nothing in the check builds, loads or publishes anything.

  Identity is the note's explicit id, written in full as an https address. An identity is never made from a file name or a path, so a typed note
  with no id is a problem, not a note whose id is guessed. Every key must be known: the profile's own keys, the relation types the profile
  allows, or a key the site declared in its root context. A link is a quoted wiki link in front matter that names exactly one typed note, and
  the two notes must be allowed to have that link. A link is stated once, as a key or as a Relation note, never both.

  Scenario: A pile of plain notes is a valid pod at level 0
    Given a folder of plain notes with no front matter
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 0 (2 notes, none typed)"
    And the pod report says "ok: no problems"

  Scenario: An empty folder is a valid pod at level 0
    Given an empty pod folder
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 0 (no notes yet)"

  Scenario: Free front matter without a type is the note's own and is left alone
    Given a folder of plain notes with no front matter
    And the pod file "notes/style.md" has this text:
      """
      ---
      title: Style guide
      next: whatever the owner likes
      ---
      A working note.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 0 (3 notes, none typed)"

  Scenario: The fixture pod is a valid level 1 pod
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 1 (10 of 12 notes typed)"
    And the pod report says "ok: no problems"

  Scenario: Checking changes nothing and contacts nothing
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "tagged_with" replaced by "tagedWith"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod folder is exactly as it was
    And no site, network or sign-in was touched

  Scenario: A typed note without an id is refused and no id is made from its name
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      type: papyrus:Article
      title: Slow water
      ---
      Words.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has a type and no id" for the note "slow-water.md"
    And the pod report says "An id is never made from the file name"
    And the pod folder is exactly as it was

  Scenario: An id without a type is refused
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0011
      title: Slow water
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has an id and no type" for the note "slow-water.md"

  Scenario Outline: An id that is not a full https address is refused
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: <id>
      type: papyrus:Article
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "not an https address" for the note "slow-water.md"

    Examples:
      | id                                               |
      | urn:uuid:sample-0011    |
      | http://example.org/id/5f0c2c1e                   |
      | slow-water                                       |
      | https://example.org/                             |

  Scenario: Two notes with the same id are both named
    Given a started pod
    And the pod file "a.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0011
      type: papyrus:Article
      ---
      """
    And the pod file "b.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0011
      type: papyrus:Article
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has the same id as b.md" for the note "a.md"
    And the pod report names the problem "has the same id as a.md" for the note "b.md"

  Scenario: An id that changed since the last commit is refused
    Given a copy of the fixture pod
    And the pod is a git repository with everything committed
    And the id of the pod note "articles/slow-water.md" is changed
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report says "ids are compared with the last commit"
    And the pod report names the problem "its id changed since the last commit" for the note "articles/slow-water.md"

  Scenario: Renaming a note does not change its identity, only the links that name its file
    # Links name a note by its file name, so the owner updates the links that named the old name; the note's id, which is its identity, stays.
    Given a copy of the fixture pod
    And the pod is a git repository with everything committed
    And the pod note "articles/slow-water.md" is renamed to "articles/water-that-stays.md"
    And the pod file "relations/report-supports-article.md" has "[[slow-water]]" replaced by "[[water-that-stays]]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: A new note that was never committed is not compared with history
    Given a copy of the fixture pod
    And the pod is a git repository with everything committed
    And the pod file "articles/new.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0012
      type: papyrus:Article
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: A pod outside git says that ids were not compared
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod check POD"
    Then the pod report says "ids are not compared with earlier commits"

  Scenario: An unknown key is refused, with the nearest known key
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "tagged_with" replaced by "tagedWith"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has the unknown key 'tagedWith'; did you mean 'tagged_with'?" for the note "articles/slow-water.md"

  Scenario: The old page type is refused and the new spelling is named
    Given a started pod
    And the pod file "about.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0011
      type: page
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has the unknown type 'page'" for the note "about.md"
    And the pod report says "did you mean papyrus:Page?"

  Scenario: A site's own keys are real keys once the root context declares them
    Given a copy of the fixture pod
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: A key nobody declared is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "eyebrow: Field notes" replaced by "kicker: Field notes"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has the unknown key 'kicker'" for the note "articles/slow-water.md"
    And the pod report says "a site declares its own keys in context.jsonld"

  Scenario: A site key holds the type the root context gave it
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "order: 2" replaced by "order: second"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'order' takes a whole number" for the note "articles/slow-water.md"

  Scenario: A site cannot redefine a profile key
    Given a copy of the fixture pod
    And the pod file "context.jsonld" has "\"eyebrow\": \"site:eyebrow\"," replaced by "\"title\": \"site:title\","
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'title' is already defined by the Papyrus profile" for the note "context.jsonld"

  Scenario: A nested value is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "authors: [Ada Example]" replaced by "authors: {name: Ada Example}"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'authors' has a nested value" for the note "articles/slow-water.md"
    And the pod report says "make a note of its own for it and link to that note"

  Scenario: A list inside a list is a nested value too
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "tags: [water, irrigation]" replaced by "tags: [[water], [irrigation]]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'tags' has a nested value" for the note "articles/slow-water.md"

  Scenario: A link where text belongs is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "title: Slow water" replaced by "title: \"[[irrigation]]\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'title' is a link where text belongs" for the note "articles/slow-water.md"

  Scenario: Text where a link belongs is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "see_also: [\"[[acme-report]]\"]" replaced by "see_also: acme-report"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'see_also' is text where a link belongs" for the note "articles/slow-water.md"

  Scenario: A list where one value belongs is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "title: Slow water" replaced by "title: [Slow, water]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'title' takes one value, not a list" for the note "articles/slow-water.md"

  Scenario: A link that names no note is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "[[irrigation]]" replaced by "[[drip-irrigation]]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "links to [[drip-irrigation]], which names no note in the pod" for the note "articles/slow-water.md"

  Scenario: A link that names two notes is refused and the path-qualified link is accepted
    Given a copy of the fixture pod
    And the pod file "sources/water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0013
      type: papyrus:Reference
      url: https://example.org/water
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "which names 2 notes (sections/water, sources/water)" for the note "articles/slow-water.md"
    When the pod file "articles/slow-water.md" has "\"[[water]]\"" replaced by "\"[[sections/water]]\""
    And I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: A link to an untyped note is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "[[irrigation]]" replaced by "[[about]]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "links to about.md, which is not a typed note" for the note "articles/slow-water.md"

  Scenario: Words on a link stay out of front matter
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "[[irrigation]]" replaced by "[[irrigation|the old way]]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "which carries words or a heading" for the note "articles/slow-water.md"
    And the pod report says "Words about a link go in a Relation note"

  Scenario: A section must be a Section note
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "section: \"[[water]]\"" replaced by "section: \"[[irrigation]]\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'section' names concepts/irrigation.md, which is not a Section note" for the note "articles/slow-water.md"

  Scenario: A link its two notes may not have is refused
    Given a copy of the fixture pod
    And the pod file "concepts/irrigation.md" has "aliases: [watering]" replaced by "cites: [\"[[acme-report]]\"]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "'cites' cannot link a Concept to a Reference" for the note "concepts/irrigation.md"

  Scenario: A symmetric link may be written from either end
    Given a copy of the fixture pod
    And the pod file "concepts/irrigation.md" has "aliases: [watering]" replaced by "related_to: [\"[[slow-water-concept]]\"]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  Scenario: A link stated twice in front matter is refused
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "[\"[[acme-report]]\"]" replaced by "[\"[[acme-report]]\", \"[[acme-report]]\"]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "states the link 'see_also'" for the note "articles/slow-water.md"
    And the pod report says "A link is stated once, as a key or as a note"

  Scenario: A link stated as a key and as a Relation note is refused
    Given a copy of the fixture pod
    And the pod file "sources/acme-report.md" has "tagged_with: [\"[[irrigation]]\"]" replaced by "supports: [\"[[slow-water]]\"]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "states the link 'supports'" for the note "sources/acme-report.md"

  Scenario: A symmetric link written from both ends is stated twice
    Given a copy of the fixture pod
    And the pod file "concepts/irrigation.md" has "aliases: [watering]" replaced by "related_to: [\"[[slow-water-concept]]\"]"
    And the pod file "concepts/slow-water-concept.md" has "broader_than: [\"[[irrigation]]\"]" replaced by "related_to: [\"[[irrigation]]\"]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "states the link 'related_to'" for the note "concepts/slow-water-concept.md"

  Scenario: A Reference without an address is refused
    Given a copy of the fixture pod
    And the pod file "sources/acme-report.md" loses the text "url: https://example.org/reports/water"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "is a Reference and has no url" for the note "sources/acme-report.md"

  Scenario: An outside address must be a web address
    Given a copy of the fixture pod
    And the pod file "sources/acme-report.md" has "url: https://example.org/reports/water" replaced by "url: reports/water"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'url' takes an outside address" for the note "sources/acme-report.md"

  Scenario: A Relation note with a missing end is refused
    Given a copy of the fixture pod
    And the pod file "relations/report-supports-article.md" loses the text "to: \"[[slow-water]]\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "is a Relation note and has no to" for the note "relations/report-supports-article.md"

  Scenario: A Relation note names a relation the profile has
    Given a copy of the fixture pod
    And the pod file "relations/report-supports-article.md" has "papyrus:supports" replaced by "papyrus:quality_rating_is"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'relation' is 'papyrus:quality_rating_is'" for the note "relations/report-supports-article.md"

  Scenario: A Relation note has one of three states
    Given a copy of the fixture pod
    And the pod file "relations/report-supports-article.md" has "state: suggested" replaced by "state: maybe"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'state' is 'maybe'; a state is one of current, suggested, rejected" for the note "relations/report-supports-article.md"

  Scenario: The two ends of a Relation note must be allowed to have that relation
    Given a copy of the fixture pod
    And the pod file "relations/report-supports-article.md" has "from: \"[[acme-report]]\"" replaced by "from: \"[[irrigation]]\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "'supports' cannot link a Concept to an Article" for the note "relations/report-supports-article.md"

  Scenario: Keys that belong to a Relation note are refused on other notes
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "order: 2" replaced by "state: current"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'state' belongs to a Relation note" for the note "articles/slow-water.md"

  Scenario: A typed note needs the root context
    Given a folder of plain notes with no front matter
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0011
      type: papyrus:Article
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report says "the pod has no context.jsonld; run `papyrus pod init` to make it a level 1 pod"

  Scenario: A context file edited by hand is not the profile
    Given a copy of the fixture pod
    And the pod file "papyrus.context.jsonld" has "\"title\": \"schema:name\"" replaced by "\"title\": \"schema:headline\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "is not profile version 2" for the note "papyrus.context.jsonld"

  Scenario: A missing generated context is reported
    Given a copy of the fixture pod
    And the pod file "papyrus.context.jsonld" is removed
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "is missing; it is generated by `papyrus pod init`" for the note "papyrus.context.jsonld"

  Scenario: A root context without an id base is reported
    Given a copy of the fixture pod
    And the pod file "context.jsonld" loses the text "\"@base\": \"https://example.org/id/\","
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "does not name the id base" for the note "context.jsonld"

  Scenario: Front matter that is not YAML is refused
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      title: [unclosed
      ---
      Words.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "front matter is not valid YAML" for the note "slow-water.md"

  Scenario: Front matter that is never closed is refused
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      title: Slow water
      Words.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "never closed with a second ---" for the note "slow-water.md"

  Scenario: A repeated key is refused
    Given a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0011
      type: papyrus:Article
      title: One
      title: Two
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "the key 'title' appears twice" for the note "slow-water.md"

  Scenario: Hidden folders and files that are not Markdown are not part of the pod
    Given a copy of the fixture pod
    And the pod file ".hidden/broken.md" has this text:
      """
      ---
      type: nonsense
      ---
      """
    And the pod file "articles/slow-water.png" has this text:
      """
      not a note
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 1 (10 of 12 notes typed)"

  Scenario: A folder that does not exist is a failed command, not a failed pod
    When I run the pod command "papyrus pod check /no/such/folder"
    Then the pod command exits with status 2
    And the pod report says "is not a folder"

  Scenario: Checking needs a folder
    When I run the pod command "papyrus pod check"
    Then the pod command fails with the message "papyrus pod check requires POD"
