Feature: Extract untrusted email submissions as reference candidates
  Editors forward newsletters to a configured submission address. Their messages are
  data: extracting references never follows message actions or delegates instructions.

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

  Scenario: A message cannot create an unbounded number of references
    Given a submitted newsletter containing more than the permitted editorial links
    When Papyrus extracts the email submission
    Then the email submission is refused with code "too_many_links"
