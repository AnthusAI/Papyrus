@reference-identity
Feature: One identity gate for References
  The same document arrives again and again: from different monitors, an editor's paste, an email, a research assignment, a chat request,
  a catalog import and the citation list of a paper. A Reference has an identity: its canonical URL, its arXiv id, its DOI, and the hash of its
  captured text. When a document the publication already holds arrives, every way of creating a Reference returns the one it holds and writes
  nothing; a held Reference keeps the curation status an editor gave it, and an accepted Reference is never reset to pending. The same title
  alone is not identity. The duplicates report only reads.

  Scenario Outline: Every form of one page is one identity
    Given a Reference for the address "https://example.org/a/b"
    When a source arrives as "<form>"
    Then the two share an identity key

    Examples:
      | form                                                   |
      | HTTPS://Example.ORG/a/b#section                        |
      | http://example.org/a/b                                 |
      | https://www.example.org/a/b/                           |
      | https://example.org:443/a/b?utm_source=feed&fbclid=1   |

  Scenario: A different path or query is a different page
    Given a Reference for the address "https://example.org/a/b"
    When a source arrives as "https://example.org/a/b?page=2"
    Then the two share no identity key

  Scenario Outline: Every arXiv form of one paper is one identity
    Given a Reference for the address "https://arxiv.org/abs/2401.01234v2"
    When a source arrives as "<form>"
    Then the two share an identity key

    Examples:
      | form                                       |
      | https://arxiv.org/pdf/2401.01234v3         |
      | https://arxiv.org/pdf/2401.01234.pdf       |
      | https://arxiv.org/html/2401.01234v1        |
      | https://doi.org/10.48550/arXiv.2401.01234  |

  Scenario Outline: Every form of one DOI is one identity
    Given a Reference for the address "https://doi.org/10.1145/3290605.3300233"
    When a source arrives as "<form>"
    Then the two share an identity key

    Examples:
      | form                                                  |
      | doi:10.1145/3290605.3300233                           |
      | https://dx.doi.org/10.1145/3290605.3300233            |
      | https://dl.acm.org/doi/pdf/10.1145/3290605.3300233    |

  Scenario: The same captured text is one identity only when it was fully captured
    Given a fully captured Reference whose text has a hash
    When another fully captured Reference has text with the same hash
    Then the two share an identity key
    And a thinly captured Reference with that hash shares none

  Scenario: The same title alone is not identity
    Given a Reference titled "Scaling Laws, Revisited" at "https://example.org/one"
    When a source titled "scaling laws revisited" arrives at "https://other.example/two"
    Then the two share no identity key
    And the report counts them as a same-title candidate and not as a duplicate

  Scenario Outline: Each way of creating a Reference uses the gate
    Given a publication that holds an accepted Reference for "https://arxiv.org/abs/2401.01234v2"
    When the <path> brings "https://arxiv.org/pdf/2401.01234v3" to the <corpus> corpus
    Then no Reference is created
    And the held Reference is still accepted
    And the held Reference is returned or reported

    Examples:
      | path             | corpus |
      | monitor delivery | same   |
      | monitor delivery | other  |
      | editor intake    | same   |
      | editor intake    | other  |
      | research intake  | same   |
      | research intake  | other  |
      | chat create      | same   |
      | chat create      | other  |
      | catalog import   | same   |
      | catalog import   | other  |
      | citation graph   | same   |
      | citation graph   | other  |

  Scenario: A document nobody holds is still created
    Given a publication that holds an accepted Reference for "https://example.org/something-else"
    When the editor intake offers "https://example.org/a-new-paper" as a new source
    Then one Reference is created and it is pending

  Scenario: Research intake run again never resets an accepted Reference to pending
    Given a publication that holds an accepted Reference for "https://example.org/a-paper"
    When research intake proposes "https://example.org/a-paper" twice
    Then no Reference is created
    And the held Reference is still accepted

  Scenario: The duplicates report groups by identity and writes nothing
    Given a publication with three forms of one paper and two same-titled pages
    When the duplicates report runs
    Then it finds one identity group with two extra rows
    And it counts one same-title group of candidates that are not one identity
    And nothing in the publication was written or changed
