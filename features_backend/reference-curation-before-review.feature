@backend @reference-curation
Feature: References are curated before an editor reviews them
  An editor rating a Reference up or down needs to know that Papyrus actually captured the item. When
  the monitoring router delivers a Reference as pending, Papyrus reads the whole source, records signals
  about how complete the capture looks, writes a summary, and, for a research paper, extracts the paper's
  structure with GROBID. None of that decides anything: the Reference stays pending, and the editor can
  correct what was captured. Each correction is kept as a new version next to the original and leaves a
  label that a future completeness classifier can learn from.

  Background:
    Given a site with a pending Reference whose source is a news article
    And a model that summarizes in source voice

  Scenario: A delivered Reference has its text and summary before the editor sees it as ready
    When the router delivers the Reference and the curation procedure it started runs
    Then the router did not wait for the curation
    And the Reference's curation card is "ready"
    And the card holds the article's full text with its word count
    And the card holds the completeness signals as facts and no completeness verdict
    And the card holds a summary written by "gpt-6-luna"
    And the Reference is still pending

  Scenario: A Reference whose source cannot be read says so instead of waiting silently
    Given the source refuses the request as "blocked"
    When the curation procedure runs for the Reference
    Then the Reference's curation card is "capture_failed"
    And the capture failure is "blocked" and the card holds no text

  Scenario: A journal landing page that fronts a PDF is captured from the PDF, not from its blurb
    Given the source is a journal landing page whose only text is its one-line description
    And the landing page declares its full text with "citation_pdf_url"
    When the curation procedure runs for the Reference
    Then the Reference's curation card is "ready"
    And the card's text is the PDF's text and not the one-line description
    And the capture records the full-text address the text came from

  Scenario: A landing page without citation metadata is followed through its alternate PDF link or its PDF anchor
    Given the source is a journal landing page whose only text is its one-line description
    And the landing page declares its full text with "alternate_pdf"
    When the curation procedure runs for the Reference
    Then the card's text is the PDF's text and not the one-line description
    And the capture records the full-text address the text came from

  Scenario: A landing page that only links a PDF in its body text is followed through the anchor
    Given the source is a journal landing page whose only text is its one-line description
    And the landing page declares its full text with "linked_pdf"
    When the curation procedure runs for the Reference
    Then the card's text is the PDF's text and not the one-line description

  Scenario: An article with real text keeps its own text even when it links a PDF
    Given the source is an article that also links a PDF
    When the curation procedure runs for the Reference
    Then the card holds the article's full text with its word count
    And the capture records no full-text address

  Scenario: A full-text link that cannot be read leaves the page's own text in place
    Given the source is a journal landing page whose only text is its one-line description
    And the landing page declares its full text with "alternate_pdf" but the file is gone
    When the curation procedure runs for the Reference
    Then the card's text is the one-line description
    And the capture records no full-text address

  Scenario: The backfill reports how many bodies are shorter than 500 characters
    Given a corpus with 2 pending References, 1 accepted Reference and 1 Reference in another corpus
    And one of the pending References has a source with only a short body
    When the backfill runs for the pending References
    Then the backfill counts 1 short body and still curated both References

  Scenario: A research paper gets its GROBID fields
    Given the Reference is an arXiv paper and a GROBID service is available
    When the curation procedure runs for the Reference
    Then the card holds GROBID fields with 2 authors, 2 sections and 1 reference
    And the GROBID title, authors, abstract, sections and references are stored with the Reference

  Scenario: A research paper without a GROBID service is a typed skip
    Given the Reference is an arXiv paper and no GROBID service is configured
    When the curation procedure runs for the Reference
    Then the card says GROBID was skipped as "grobid_not_configured"
    And the Reference's curation card is "ready"

  Scenario: A paper's GROBID extraction is picked up once a service exists
    Given the Reference is an arXiv paper and no GROBID service is configured
    And the curation procedure has run for the Reference
    When a GROBID service becomes available and the curation procedure runs again
    Then the card holds GROBID fields with 2 authors, 2 sections and 1 reference
    And the model was asked for a summary only once

  Scenario: An editor's correction is a new version that keeps the original
    Given the curation procedure has run for the Reference
    When the editor "editor-one" pastes the full text "The complete article, pasted by an editor." and labels the capture "incomplete"
    Then the original captured text is unchanged
    And the correction is stored as version 1 "edited by editor" by "editor-one"
    And the card shows the correction as the current text
    And the label records that the original capture was "incomplete" with its signals
    And the summary is marked stale until the next curation run

  Scenario: An editor uploads the PDF they downloaded and its text becomes the Reference's text
    Given the curation procedure has run for the Reference
    When the editor "editor-one" uploads a PDF of a research paper and labels the capture "incomplete"
    Then the PDF's text is stored as version 1 "edited by editor" by "editor-one", marked as coming from an uploaded PDF
    And the original captured text is unchanged
    And the card says whether it is a research paper, so the next curation run can decide on GROBID
    And the summary is marked stale until the next curation run

  Scenario: An upload that cannot give us text is refused in plain words and changes nothing
    Given the curation procedure has run for the Reference
    When the editor uploads a file that is not a PDF, a PDF with no text, or a PDF uploaded to another Reference
    Then each is refused saying what is wrong, and the card still shows the original text

  Scenario: The next curation run summarizes the corrected text and never recaptures over it
    Given the curation procedure has run for the Reference
    And the editor "editor-one" pasted the full text "The complete article, pasted by an editor." and labeled the capture "incorrect"
    When the curation procedure runs for the Reference
    Then the model summarized "The complete article, pasted by an editor."
    And the source was not fetched again

  Scenario: A YouTube video is captured from its transcript
    Given the Reference is a YouTube video whose page only has a short description
    And YouTube gives the transcript of the video
    When the curation procedure runs for the Reference
    Then the Reference's curation card is "ready"
    And the card's text is the video's transcript and not the short description
    And the capture records that the text came from the YouTube transcript

  Scenario: A YouTube video whose transcript is blocked falls back to its description and says why
    Given the Reference is a YouTube video whose page only has a short description
    And YouTube blocks the request for the transcript
    When the curation procedure runs for the Reference
    Then the card's text is the video's short description
    And the capture records that the text came from the video description because the transcript was "blocked"

  Scenario: A YouTube video without a transcript falls back to its description and says why
    Given the Reference is a YouTube video whose page only has a short description
    And the video has no transcript
    When the curation procedure runs for the Reference
    Then the card's text is the video's short description
    And the capture records that the text came from the video description because the transcript was "no_transcript"

  Scenario: The backfill curates existing pending References once
    Given a corpus with 2 pending References, 1 accepted Reference and 1 Reference in another corpus
    When the backfill runs for the pending References
    Then 2 References were curated and the others were left alone
    When the backfill runs for the pending References again
    Then no Reference was curated and nothing was written

  Scenario: The backfill dry run only reports
    Given a corpus with 2 pending References, 1 accepted Reference and 1 Reference in another corpus
    When the backfill runs as a dry run
    Then it plans 2 References and writes nothing
