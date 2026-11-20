Feature: Forwarded newsletters become Reference candidates and are never obeyed
  Editors forward newsletters to the publication's submission address. Papyrus treats each message as data: it pulls out the
  editorial links as Reference candidates, keeps private where each one came from, and never follows an action or an instruction
  written in the message. Tracking variants of one link are one candidate, automatic replies are not submissions, and a long
  newsletter loses none of its links.

  Scenario: Multipart newsletter retains editorial links and private provenance
    Given a submitted multipart newsletter with editorial links and account actions
    When Papyrus extracts the email submission
    Then the submission has two distinct editorial links and sender provenance
    And email instructions and attachment links are not reference candidates

  Scenario: Tracking variants of a link identify one candidate
    Given a submitted plain text newsletter with duplicate tracking variants
    When Papyrus extracts the email submission
    Then the submission has one canonical editorial link

  Scenario: Automatic responses do not become new submissions
    Given a submitted automatic response containing an editorial link
    When Papyrus extracts the email submission
    Then the email submission is refused with code "automated_message"

  Scenario: All eligible links survive more than one internal work batch
    Given a submitted newsletter containing 41 unique editorial links
    When Papyrus extracts the email submission
    Then all 41 eligible links are retained for resumable intake

  Scenario: An explicitly supplied safe resolver unwraps only synthetic article redirects
    Given a synthetic Beehiiv article link and an unsubscribe action link
    When Papyrus extracts with an offline synthetic redirect adapter
    Then only the normalized final article URL is retained
    And the adapter pins public addresses without following redirects or reading bodies
