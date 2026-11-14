Feature: People write notes on a Story as themselves, and AI agents write agent notes
  A note on a Story is a person's Message. Signed in, the newsroom stamps the author from the sign-in, so a note names the person who
  wrote it and never a label someone typed. A note that could not be saved is reported as a failure, in one honest line, with a
  non-zero exit code, and never prints that it wrote anything. An AI agent does not write Messages. It saves an agent note, kept as an
  attachment owned by the Story and labelled as AI; the newsroom records who ran the agent from the sign-in and keeps the agent's name
  as a label. Only editors and admins can add one. An agent that works under a person's own login cannot be told apart from the person
  by the newsroom, so for a person's note that rule rests on the agent's instructions.

  Background:
    Given a Story with two saved versions

  Scenario: A signed-in person's note is stamped with their identity, not a supplied label
    When a signed-in editor adds the note "Corroborated by the vendor post." and supplies the author label "ChatGPT"
    Then the note is posted through the postMessage mutation, which has no author argument
    And no author label was sent to the newsroom
    And the command warns that the label is ignored
    And the command prints its write line after the note was saved

  Scenario: A note that could not be saved prints no write line and fails
    When a signed-in editor adds a note and the newsroom refuses it as not authorized
    Then the command prints no write line
    And the command fails with the one-line message "The note was not saved: GraphQL request failed: Not Authorized to access postMessage on type Mutation"

  Scenario: A dry run prints its dry run line and writes nothing
    When a signed-in editor adds a note as a dry run
    Then the command prints a dry run line
    And no record is written

  Scenario: A note written with an operator's AWS credentials does not claim a person wrote it
    When an operator adds a note with the author label "ops" on the IAM lane
    Then the message is a system message from an operator labelled "ops"

  Scenario: An agent note is listed by stories show, labelled as AI
    Given an AI agent named "ChatGPT" has saved the note "Vercel corroborates the disclosure."
    When a signed-in editor shows the Story
    Then the show output has an "agent-note" line for "AI agent ChatGPT"

  Scenario: Adding an agent note is open to editors and admins only
    Then the addStoryAgentNote mutation is authorized for the editor and admin groups and no others
    And an agent note from a caller with no sign-in is refused

  Scenario: An agent note that names no agent or has no text is refused
    When an AI agent saves an empty note
    Then the agent note is refused and nothing is written
