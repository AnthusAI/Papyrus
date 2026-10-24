Feature: Shared newsroom chat presentation
  Papyrus supplies authenticated console data and editorial actions while
  Chatticus supplies the transcript, markdown and composer behavior.

  Scenario: Read and send an editorial message through the shared surface
    Given Papyrus supplies an editorial conversation to the shared chat
    When the editor sends a new console message
    Then the Papyrus adapter receives the message once and shows its reply
    And the shared surface renders the assistant markdown safely

  Scenario: Send another message while the assistant reply is running
    Given Papyrus supplies an editorial conversation to the shared chat
    And the assistant is still replying to the previous message
    When the editor sends a new console message
    Then the Papyrus adapter receives the message once and shows its reply

  Scenario: Send a keyboard message once
    Given Papyrus supplies an editorial conversation to the shared chat
    When the editor sends a new console message with the keyboard
    Then the Papyrus adapter receives the message once and shows its reply

  Scenario: Keep disabled sends out of the Papyrus adapter
    Given Papyrus supplies an editorial conversation to the shared chat
    And Papyrus has temporarily disabled sending
    When the editor attempts to send a message with the keyboard
    Then Papyrus receives no message

  Scenario: Keep editorial actions in Papyrus
    Given Papyrus supplies an editorial conversation to the shared chat
    When the editor selects a tool's reference action
    Then Papyrus handles that reference action without a Chatticus account

  Scenario: Enforce the site host trust and transcript ownership contract
    When the shared chat admission contract rejection suite runs
    Then wrong trust profiles, inactive memberships and foreign transcript owners are rejected

  Scenario: Replay an admitted send once within its private editor scope
    When the shared chat admission contract rejection suite runs
    Then an identical retry returns the original result and a changed payload conflicts

  Scenario: Retry one Chatticus admission explicitly with fresh Papyrus auth
    When Papyrus retries an uncertain Chatticus admission
    Then it reuses the logical message key and body with newly obtained auth headers

  Scenario: Route private newsroom chat through the hosted Chatticus core
    When the Papyrus hosted chat endpoint contract suite runs
    Then account and editor scope come from the sealed session and private channel access is enforced

  Scenario: Keep the private chat route off until a site explicitly enables it
    When the Papyrus hosted chat endpoint contract suite runs
    Then the hosted chat route remains disabled until explicitly enabled

  Scenario: Open a private newsroom conversation and complete a shared worker turn
    When the Papyrus shared worker integration suite runs
    Then the sealed editor creates the private channel and sees one persisted reply after refresh and replay

  Scenario: Use the shared console UI with the private hosted runtime
    When the private console browser integration runs
    Then same-origin sends retain editor session scope, allow a pending-reply send and render the hosted reply
