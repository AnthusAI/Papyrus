Feature: Inbound email has one reader and reports a filing it could not do
  Inbound mail is read by one MIME reader. It used to be read by a part scanner and, when that found nothing useful, by a second
  parser whose text, subject and links were substituted, and links were then scraped out of the raw bytes of the whole message,
  attachments included. A PDF or attachment that could not be filed used to be handed to a chat agent, which answered the sender as if
  the filing had gone as planned. Now the reader reads the message structure once, and a filing that fails fails the message: the
  sender receives the reason by email and the message is marked failed. Replies that are conversation stay conversation.

  Scenario: A PDF that cannot be filed fails the message and tells the sender why
    Given an authorized PDF-only submission whose filing fails
    When the submission is processed
    Then the message is marked failed with the filing's reason
    And the sender is sent that reason
    And no chat agent is started for it

  Scenario: An attachment-only reply that cannot be filed fails the message and tells the sender why
    Given an authorized attachment-only reply whose filing fails
    When the submission is processed
    Then the message is marked failed with the filing's reason
    And the sender is sent that reason
    And no chat agent is started for it

  Scenario: Single-part, multipart and HTML-only messages are read by the one reader
    Given the inbound MIME reader test for the Lambda
    When it reads a phone's single-part message, a nested multipart message with an attachment, an HTML-only message and a message with no text
    Then the text and links come from the message's own text parts only, and a message with no text part yields no body and no links
