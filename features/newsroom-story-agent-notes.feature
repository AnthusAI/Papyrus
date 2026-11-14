@brand-agnostic
Feature: A story's Messages view shows the notes AI agents wrote, labelled as AI
  An agent that works on a story records what it found with `papyrus stories agent-note`. The note is kept on the story as an
  attachment, never as a Message, and Messages come only from people. The story's Messages view puts each agent note in the same
  list as the people's notes, newest first, and marks it as AI in words ("AI agent" and the agent's name) and with an icon, never
  by colour alone. A note a person wrote carries no AI mark. The mark is a flat tinted block, with no border or outline. These
  scenarios run in demo mode with in-memory data.

  Scenario: An agent note is marked as AI in words and with an icon
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's Messages view
    Then the Messages view should list 2 agent notes
    And each agent note should be marked "AI agent" with an icon and name its agent
    And the agent note from "ChatGPT" should show its summary

  Scenario: Agent notes and people's notes are in one list by time
    Given I open the demo story that is based on a Reference at 1280 by 900
    When I open the story's Messages view
    Then the Messages list should be ordered newest first as "ChatGPT", "ryan", "Claude"
    And the note from "ryan" should have no AI mark

  Scenario: The AI mark has no border or outline on a phone
    Given I open the demo story that is based on a Reference at 375 by 812
    When I open the story's Messages view
    Then each agent note should have no border or outline
