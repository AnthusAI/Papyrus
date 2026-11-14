Feature: Knowledge queries count tokens exactly or stop
  A knowledge query keeps its context inside a token budget. It counts with tiktoken. It used to count words and punctuation marks
  when tiktoken was missing and add a warning to the answer, so a budget could be wrong by a wide margin without anyone seeing it.
  tiktoken is a declared dependency; when it cannot load, the query stops with that error. The same holds when a related message
  cannot be resolved: the query raises instead of treating the message as empty. These scenarios run the real functions.

  Scenario: The token counter counts with tiktoken and has no approximate mode
    Given the token counter
    When it counts and truncates a sentence
    Then the count equals tiktoken's count, truncation stays within the budget, and the counter has no regex or switch-off mode

  Scenario: A tiktoken that cannot load stops the query
    Given the token counter
    When the tokenizer model is one tiktoken does not know
    Then counting raises tiktoken's error and no approximate count is returned

  Scenario: A related message that cannot be resolved stops the query
    Given a graph whose message lookup fails
    When a reference summary is read through a relation
    Then the lookup error reaches the caller
