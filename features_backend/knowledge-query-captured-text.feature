Feature: A knowledge query reads the text a person or an agent captured for a Reference
  An editor, or an AI agent working for one, can capture the text of a Reference that the
  automatic capture could not get (the signed-in `correctReferenceCapture` action). That text is
  stored as a body of the Reference version, not as the older extracted-text attachment that
  topic runs read. A researcher who queries the topic expects it to count as evidence.

  The query finds the Reference's current text through the Reference's own attachments, one
  Reference at a time, and never reads a whole table. When a person has corrected the text,
  the correction is the current text and it beats the extracted-text attachment it replaced.
  When nobody corrected it, the extracted-text attachment is used if there is one, and the
  machine capture is used when it is all that exists. Text the caller is not allowed to
  download is never returned, and the query says so in its warnings instead of quietly
  answering from metadata alone. Text that an agent captured carries who captured it and the
  note that came with it, for example that nobody has independently checked it is complete.

  Scenario: A captured Reference supplies evidence to a knowledge search
    Given an accepted Reference whose captured text was supplied by an agent
    When a researcher queries the relevant topic
    Then the query returns evidence passages from the captured text
    And the evidence names the agent and keeps its note that the text is not independently checked

  Scenario: A corrected capture supersedes an older one
    Given an accepted Reference whose captured text was replaced by a second correction
    When a researcher queries the relevant topic
    Then the query returns passages from the second correction only
    And the evidence is attributed to the editor who made the second correction

  Scenario: A person's correction beats the extracted text it replaced
    Given an accepted Reference with an extracted-text attachment and a later editor correction
    When a researcher queries the relevant topic
    Then the query returns passages from the correction
    And the extracted-text attachment is not read

  Scenario: Without a correction the extracted text is used
    Given an accepted Reference with an extracted-text attachment and only a machine capture
    When a researcher queries the relevant topic
    Then the query returns passages from the extracted-text attachment

  Scenario: Text the caller may not download is reported, not returned
    Given an accepted Reference whose captured text the caller is not allowed to download
    When a researcher queries the relevant topic
    Then the query returns no passages from it
    And the warnings say the captured text exists but could not be read

  Scenario: A recorded text that has no active attachment is reported
    Given an accepted Reference whose captured text attachment was deleted
    When a researcher queries the relevant topic
    Then the query returns no passages from it
    And the warnings say no active attachment was found for the captured text

  Scenario: The query finds the text by the Reference's own attachments
    Given an accepted Reference whose captured text was stored under an attachment id the client would not compute
    When a researcher queries the relevant topic
    Then the query returns evidence passages from the captured text
    And only that Reference's attachments were listed

  Scenario: The signed-in CLI reads the current captured text with the writer's identifier
    Given a Reference with a long identifier whose correction the upload function stored
    When the signed-in CLI reads the current text of that Reference
    Then the CLI gets the corrected text
    And the same holds for the attachment identifier the client computes for any identifier length
