Feature: Topic modeling on recent References, as one operation
  An editor agent that wants to know what the newsroom's recent References are about asks for their topics. The ask is one operation in one table,
  src/papyrus_content/topics/operations.py: the command papyrus topics model, the MCP tool topics_model, the newsroom's TypeScript types, the topic-work
  skill's reference block and docs/topics.md are all generated from that table, so they cannot disagree. Both the command and the tool only turn what
  they are given into the operation's input and pass it to the same function. That function reads the References of a window of days on their source
  date (features_backend/reference-source-date-index.feature), models the References of that window and of the window just before it together, and
  gives back a compact list: per topic a label, the top terms, a count, a trend as a word and a mark (never colour alone), a few representative
  References, and one saved id for the run. It publishes nothing and changes no record. The engine is BERTopic through Biblicus with the weekly
  knowledge run's settings, behind a small interface; these scenarios use a deterministic fake, so nothing here calls a model or the network.

  Scenario: The generated files are exactly what the table produces
    Then the generated command spec, MCP schema, TypeScript types, skill reference block and docs for topics are all current
    And the topic generator's check mode reports nothing out of date

  Scenario: The window defaults to fourteen days and the presets are seven, fourteen and twenty-eight
    When a person asks for topics with no options as of 2026-11-08
    Then the window runs from 2026-10-26 to 2026-11-08 and is compared with 2026-10-12 to 2026-10-25
    And the operation offers the windows 7d, 14d and 28d and the votes pending, accepted and rejected

  Scenario: Topics come back compact, with counts, trend words and marks, and a saved id
    Given a corpus where ransomware stories became common in the last two weeks and voice stories became rarer
    When a person asks for topics as of 2026-11-08
    Then the ransomware topic has 24 References now and 6 before, and is marked rising with the mark for rising
    And the voice topic has 10 References now and 20 before, and is marked falling with the mark for falling
    And each topic shows up to three representative References, newest first, and no member lists
    And the result carries a legend that says in words what each mark means
    And the smallest topic scaled with the number of References, the square root of 60 rounded, which is 8

  Scenario: The comparison can be left out
    Given a corpus where ransomware stories became common in the last two weeks and voice stories became rarer
    When a person asks for topics with the comparison set to none
    Then only the current window is read and modeled and no topic has a trend

  Scenario: A previous window with nothing in it is said, not guessed
    Given a corpus with References only in the last two weeks
    When a person asks for topics as of 2026-11-08
    Then the warnings say the previous window is empty and no topic is marked rising or falling

  Scenario: Too few References is a plain answer, not an error
    Given a corpus with one Reference in the window
    When a person asks for topics as of 2026-11-08
    Then there are no topics and the engine was never asked
    And the warnings say there were too few References

  Scenario: The same question on the same References is answered from the store
    Given a corpus where ransomware stories became common in the last two weeks and voice stories became rarer
    When a person asks for topics as of 2026-11-08 twice
    Then the engine was asked once and the second answer says it was cached with the same saved id
    When one Reference is updated and the question is asked again
    Then the engine is asked again and the saved id is different
    When the question is asked again with refresh
    Then the engine is asked again

  Scenario: The command and the MCP tool give identical JSON for the same request
    Given a corpus where ransomware stories became common in the last two weeks and voice stories became rarer
    When the example input is given as a command line and as the MCP tool
    Then both answer with the same JSON, a success from the publication

  Scenario Outline: A request that does not fit is refused by name
    When a person runs the topics command "<line>"
    Then the command exits with the error code and answers <code> naming "<field>"

    Examples:
      | line                      | code          | field  |
      | model --window 90d        | invalid_input | window |
      | model --as-of yesterday   | invalid_input | asOf   |
      | model --section nowhere   | not_found     | section |
      | model --min-cluster-size 0 | invalid_input | minClusterSize |

  Scenario: An engine that cannot run saves nothing
    Given a corpus where ransomware stories became common in the last two weeks and voice stories became rarer
    And an engine that cannot run
    When a person asks for topics as of 2026-11-08
    Then the answer is engine_failed and says it may be retried
    And no topic run was saved

  Scenario: The real engine is driven the way the knowledge run drives it
    Given a Biblicus runner that records its commands and answers like Biblicus
    When the Biblicus engine models eight documents with a smallest topic of three
    Then it made a throwaway corpus, extracted the text and ran the topic analysis with the knowledge run's settings
    And its topics carry the documents' own ids and drop the outlier group
