Feature: The decision request carries the captured text once
  Cyclotron reads only the request's text. The full captured article used to travel twice, as its
  own value and again inside the text, which made large articles too big for the lab to accept.
  The request now carries the captured text only inside its text, plus the short summary.

  Scenario: A long captured article appears once, inside the text
    Given a collected story with a long captured article and a summary
    When the router builds the decision request for the enriched story
    Then the request values hold the summary but no separate body
    And the request text holds the title, the address, the summary and the whole article
    And the enriched request is valid

  Scenario: A request that carries a separate body is refused
    Given a collected story with a long captured article and a summary
    When the router builds the decision request for the enriched story
    And a separate body is added to the request values
    Then the enriched request is refused

  Scenario: A text that is not the title, address and summary is refused
    Given a collected story with a long captured article and a summary
    When the router builds the decision request for the enriched story
    And the request text is replaced by the article alone
    Then the enriched request is refused
