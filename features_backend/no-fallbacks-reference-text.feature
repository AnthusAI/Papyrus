Feature: A Reference whose article text cannot be filtered fails, and no second extractor runs
  The article text of a Reference is the filtered text. When the article-text filter failed, the commands used to store the raw
  extraction as the Reference's text, mark it "fallback_raw" and count it, so a Reference could carry navigation menus and cookie
  banners as its article. The Reference now fails with the filter's own reason, its raw extraction is kept as the raw attachment, and
  no article text is stored. In the same way, a page whose main text the capture could not read is "no text", not a second
  extractor's best guess. These scenarios run the real planner with a stand-in for the filter.

  Scenario: A failed filter fails the Reference and stores no article text
    Given a Reference with a raw extraction whose article-text filter fails
    When the article text is planned
    Then the Reference is reported as failed with the filter's reason
    And no article text attachment is planned
    And no fallback-raw count or filter-fallback list is reported

  Scenario: The page capture has one text extractor
    Given the page capture module
    Then it has no second text extractor for pages whose main text could not be read
