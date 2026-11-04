Feature: References filed by a research run have clean titles, clean addresses and honest notes
  A research run files the sources it cites as References. It used to copy the search results page's title, so a Reference was called
  "[2204.06974] Planting Undetectable Backdoorsin Machine ..." or "seL4 | Proceedings of the 2013 IEEE Symposium on Security and ...". It kept a
  publisher's session junk in the address ("?error=cookies_not_supported&code=..."), which made the same page look like two. It filed a mirror
  of an arXiv paper rather than the arXiv record. And the note stored on a Reference was printed as "Accepted because" whether it was how a
  research run found the Reference or a Cyclotron's reason for rejecting it. Now the run cleans the title and the address and prefers the
  title the source gives itself once the run has opened it, files arXiv papers at arXiv, and the context pack says what each note is.

  Scenario: A search result's title loses the arXiv id, the site's name and the ellipsis the results page added
    Given a search result titled "[2204.06974] Planting Undetectable Backdoorsin Machine ..." at "https://arxiv.org/abs/2204.06974"
    And a search result titled "seL4 | Proceedings of the 2013 IEEE Symposium on Security and ..." at "https://dl.acm.org/doi/10.1145/2517349.2522713"
    And a search result titled "Language-Based Information-Flow Security - CS@Cornell" at "https://www.cs.cornell.edu/andru/papers/jsac/sm-jsac03.pdf"
    When the results are merged into sources
    Then the source at "https://arxiv.org/abs/2204.06974" is titled "Planting Undetectable Backdoorsin Machine"
    And the source at "https://dl.acm.org/doi/10.1145/2517349.2522713" is titled "seL4"
    And the source at "https://www.cs.cornell.edu/andru/papers/jsac/sm-jsac03.pdf" is titled "Language-Based Information-Flow Security"

  Scenario: A title that merely has a dash in it is left alone
    Given a search result titled "Opening the Black Box - A Survey of Model Internals" at "https://example.org/survey"
    When the results are merged into sources
    Then the source at "https://example.org/survey" is titled "Opening the Black Box - A Survey of Model Internals"

  Scenario: The title the opened page gives itself replaces the search result's
    Given a source titled "Rice's theorem - course handout ..." at "https://notes.example.org/rice"
    And the page at "https://notes.example.org/rice" has the title "Rice's Theorem and Undecidable Program Properties | Notes"
    When the run reads the sources
    Then the source at "https://notes.example.org/rice" is titled "Rice's Theorem and Undecidable Program Properties | Notes"

  Scenario: The title in a PDF's metadata is used when the page has none
    Given a source titled "[2204.06974] Planting ..." at "https://arxiv.org/abs/2204.06974"
    And the PDF at "https://arxiv.org/pdf/2204.06974" has the metadata title "Planting Undetectable Backdoors in Machine Learning Models"
    When the run reads the sources
    Then the source at "https://arxiv.org/abs/2204.06974" is titled "Planting Undetectable Backdoors in Machine Learning Models"

  Scenario: A blocked page's title, or a file name, is not used as a title
    Given a source titled "Machine Learning Security Survey" at "https://example.org/blocked"
    And the page at "https://example.org/blocked" has the title "Just a moment..."
    And a source titled "Another Survey" at "https://example.org/doc"
    And the PDF at "https://example.org/doc" has the metadata title "Microsoft Word - survey_final.doc"
    When the run reads the sources
    Then the source at "https://example.org/blocked" is titled "Machine Learning Security Survey"
    And the source at "https://example.org/doc" is titled "Another Survey"

  Scenario: A publisher's cookie error and session id do not make the same page two sources
    Given a search result titled "Seminal paper" at "https://link.springer.com/article/10.1007/s001459900035?error=cookies_not_supported&code=a1b2c3d4"
    And a search result titled "Seminal paper" at "https://link.springer.com/article/10.1007/s001459900035"
    And a search result titled "Old portal" at "https://portal.example.org/paper;jsessionid=ABC123?id=9"
    When the results are merged into sources
    Then there are 2 sources
    And the source at "https://link.springer.com/article/10.1007/s001459900035" was found by 2 results
    And the source at "https://portal.example.org/paper?id=9" is titled "Old portal"

  Scenario: A query parameter that is not session junk is kept
    Given a search result titled "Report" at "https://example.org/report?id=42&error=none"
    When the results are merged into sources
    Then the source at "https://example.org/report?id=42&error=none" is titled "Report"

  Scenario: A mirror of an arXiv paper is filed as the arXiv record, once
    Given a search result titled "Backdoors" at "https://ar5iv.labs.arxiv.org/html/2204.06974v2"
    And a search result titled "Backdoors" at "https://arxiv.org/pdf/2204.06974v1.pdf"
    And a search result titled "Backdoors" at "https://arxiv.org/abs/2204.06974"
    When the results are merged into sources
    Then there are 1 sources
    And the source at "https://arxiv.org/abs/2204.06974" was found by 3 results

  Scenario: A page that is not on arXiv is not changed into an arXiv address
    Given a search result titled "Notes on 2204.06974" at "https://example.org/blog/2204.06974"
    When the results are merged into sources
    Then the source at "https://example.org/blog/2204.06974" is titled "Notes on 2204.06974"

  Scenario: How a research run found a Reference is not shown as why it was accepted
    Given a Reference filed pending by a research run with the note "Found by perplexity (undecidability proof): Rice's theorem"
    When the Reference is written for the context pack
    Then the Reference's note is labelled "How it was found"
    And the Reference's text does not contain "Accepted because"

  Scenario: A reason for rejecting a Reference is never shown as a reason for accepting it
    Given a Reference rejected by the Cyclotron with the note "This doesn't seem to relate to AI/ML or be a computing principle that generalizes"
    When the Reference is written for the context pack
    Then the Reference's note is labelled "Rejected because"
    And the Reference's text does not contain "Accepted because"

  Scenario: A Reference still waiting for a vote shows a reason that was written for it as how it was found
    Given a Reference filed pending by a research run with the note "This doesn't seem to relate to AI/ML"
    When the Reference is written for the context pack
    Then the Reference's note is labelled "How it was found"

  Scenario: An editor's reason on an accepted Reference is still shown as the reason it was accepted
    Given a Reference accepted by an editor with the note "The key ruling on liability"
    When the Reference is written for the context pack
    Then the Reference's note is labelled "Accepted because"

  Scenario: A Reference an editor reopened shows the note from the last decision, not an accept reason
    Given a Reference reopened by an editor after an earlier vote with the note "Not sure about this one"
    When the Reference is written for the context pack
    Then the Reference's note is labelled "Note from the last decision"

  Scenario: The discovery note of a Reference an editor accepted without a reason is still not an accept reason
    Given a Reference accepted by an editor whose only note is the discovery note "Found by perplexity (undecidability proof): Rice's theorem"
    When the Reference is written for the context pack
    Then the Reference's note is labelled "How it was found"

  Scenario: A discovery note does not rank a Reference above one with an editor's reason
    Given a Reference filed pending by a research run with the note "Found by perplexity (x): y"
    And a Reference accepted by an editor with the note "The key ruling on liability"
    Then the Reference with the editor's reason ranks ahead of the one with the discovery note
