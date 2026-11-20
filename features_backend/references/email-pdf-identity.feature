Feature: A PDF sent by email is recognized by the paper it holds
  A reader or an editor can mail a PDF to the newsroom with nothing else in the
  message. Papyrus has no link to go on, so it reads the paper's own identifier
  out of the file: a DOI, or an arXiv number. That identifier becomes the
  Reference's identity and its citation link, so the same paper mailed twice is
  one Reference, not two.

  Scenario: A paper with a DOI is identified by its DOI
    Given an emailed PDF that contains the text "Published as 10.1038/nature12373 in Nature"
    When Papyrus reads the paper's identifiers
    Then the paper's DOI is "10.1038/nature12373"
    And the Reference identity is "doi:10.1038/nature12373"
    And the citation link is "https://doi.org/10.1038/nature12373"

  Scenario: A paper with an arXiv link is identified by its arXiv number
    Given an emailed PDF that contains the text "Available at https://arxiv.org/pdf/1706.03762.pdf"
    When Papyrus reads the paper's identifiers
    Then the paper's arXiv number is "1706.03762"
    And the Reference identity is "arxiv:1706.03762"
    And the citation link is "https://arxiv.org/abs/1706.03762"

  Scenario: The version on an arXiv number is not part of the identity
    Given an emailed PDF that contains the text "arXiv preprint 2301.07041v3"
    When Papyrus reads the paper's identifiers
    Then the paper's arXiv number is "2301.07041"
    And the Reference identity is "arxiv:2301.07041"

  Scenario: A paper with both identifiers is filed under its DOI
    Given an emailed PDF that contains the text "arxiv.org/abs/1706.03762 and doi 10.5555/3295222.3295349"
    When Papyrus reads the paper's identifiers
    Then the Reference identity is "doi:10.5555/3295222.3295349"
    And the citation link is "https://doi.org/10.5555/3295222.3295349"

  Scenario: The identity does not depend on how the DOI was capitalized
    Given an emailed PDF that contains the text "doi 10.1145/ABC.DEF"
    When Papyrus reads the paper's identifiers
    Then the Reference identity is "doi:10.1145/abc.def"

  Scenario: A PDF with no identifier has no identity to file it under
    Given an emailed PDF that contains the text "Minutes of the planning meeting"
    When Papyrus reads the paper's identifiers
    Then the paper has no Reference identity
    And the paper has no citation link

  Scenario: The identifiers say how they were found
    Given an emailed PDF that contains the text "Published as 10.1038/nature12373 in Nature"
    When Papyrus reads the paper's identifiers
    Then the identifiers were found by "pdf_bytes_regex"

  Scenario: A paper mailed a second time finds the Reference that already exists
    Given the corpus already holds these References for "doi:10.1038/nature12373"
      | id          | version state |
      | ref-old     | superseded    |
      | ref-current | current       |
    When Papyrus looks for a Reference with the identity "doi:10.1038/nature12373"
    Then it finds the Reference "ref-current"
    And it asked only for that identity in that corpus

  Scenario: A paper nobody has sent before finds nothing
    Given the corpus holds no Reference for "doi:10.1038/nature12373"
    When Papyrus looks for a Reference with the identity "doi:10.1038/nature12373"
    Then it finds no Reference
