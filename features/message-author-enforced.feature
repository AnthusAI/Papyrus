@brand-agnostic
Feature: The backend stamps a message's author and moderates deletes
  A Message records who wrote it, and the backend decides that, not the browser. People read Messages through the model but write
  them only through four mutations: postMessage, editMessage, deleteOwnMessage and moderateMessage. The author of a post is the
  signed-in user's sub, whatever the client sends; an edit or a self-delete succeeds only when the stored author is the caller; an
  admin soft-deletes anyone's message with moderateMessage and cannot edit it. A conversation is renamed only by its creator or an
  admin, through renameThread. A deletion is soft, so replies keep their place. The router, procedures, the console responder,
  email and Slack write the model directly with their own grants, which this does not change. The browser's console chat posts its
  turns through postMessage too. These scenarios run the real resolvers against a stand-in for the AppSync runtime and read the
  schema the data API is built from; they deploy nothing.

  Scenario: A post records the signed-in user whatever the client sends
    Given the data API schema and its message resolvers
    When a signed-in editor posts a message that names a different author, profile and time
    Then the message is stored with the editor's own sub, the server's time and a completed response status, and never replaces an existing message

  Scenario: Nobody can edit another person's message
    Given the data API schema and its message resolvers
    When an editor, or an admin, edits a message
    Then the write only succeeds when the stored author is the caller and the message is not deleted
    And a refusal says in words that only the author can edit

  Scenario: An author cannot reassign authorship
    Given the data API schema and its message resolvers
    When any edit, delete or moderation is run
    Then none of them writes authorSub, and the model offers no update and no owner rule

  Scenario: An author deletes their own message softly
    Given the data API schema and its message resolvers
    When an author deletes their message
    Then the message stays, marked deleted with when and by whom, its text is untouched, and only the author's own message qualifies

  Scenario: An admin moderates but cannot edit
    Given the data API schema and its message resolvers
    When an admin and an editor each try to moderate a message
    Then the admin's soft delete is recorded as the admin's doing with no change to the text, and the editor is refused in words
    And moderateMessage is offered to admins only

  Scenario: Renaming a conversation is for its creator or an admin
    Given the data API schema and its message resolvers
    When an editor and an admin rename a conversation
    Then the editor's rename is conditional on being the creator, the admin's is not, and the model itself cannot change a title or a creator

  Scenario: People read the model and cannot write it
    Given the data API schema and its message resolvers
    When the rules on Message are read
    Then editors and admins can only read, and the five mutations are offered to the right groups on the right tables

  Scenario: Machine writers and the browser console chat keep working
    Given the data API schema and its message resolvers
    When the function grants and every browser writer are read
    Then the functions keep their grants and the assignment function can still create and update Messages
    And the conversation, forum and console chat writers post through postMessage and name no author

  Scenario: A site that loads the schema from the package can deploy the message resolvers
    Given the data API schema and its message resolvers
    When the resolver files are located the way a site's deploy locates them
    Then every message resolver is named by an absolute path to a file that exists, wherever the package is installed
