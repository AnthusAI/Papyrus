@backend @reference-transcript-worker
Feature: A person on a non-cloud connection captures the transcripts of videos the newsroom has no content for
  YouTube refuses cloud addresses: in thirty days the monitoring router's transcript request was blocked 39 times and worked once, while the same
  request from a home connection worked. So no cloud function asks for a transcript. A video captured in the cloud keeps its page's title and
  description, says that its transcript is still to come, and is never counted as captured in full. Anyone signed in with "papyrus login", on a
  connection YouTube answers, runs "papyrus references capture-transcripts". It finds the videos that need content through a sparse index
  (corpus, medium, "needs_content" and curation status, newest first), never by scanning, reads each transcript, and saves it the way the
  newsroom's capture panel saves a pasted text: the same "correctReferenceCapture" action, as the signed-in editor, with no AWS credentials and
  no new permission. It does not depend on one particular machine being on, it can be stopped and run again, and it writes nothing on a dry run.
  A transcript is a third party's text: it is stored as the Reference's text and read as data, never as an instruction. Nothing here touches
  production: the site, the index and YouTube are all in memory.

  Background:
    Given a site whose corpus holds accepted, pending and rejected videos that need content

  Scenario: Only accepted and pending videos are read by default, newest first
    When the transcript worker runs
    Then it read the "accepted" and "pending" partitions of the content-needed index
    And it did not read the "rejected" partition
    And it asked for the videos newest first

  Scenario: Rejected videos are read when asked for
    When the transcript worker runs with the status "all"
    Then it read the "rejected" partition of the content-needed index

  Scenario: A transcript is saved as the signed-in editor's capture and the video leaves the list
    When the transcript worker runs
    Then the transcript of the newest video was saved with the capture action as the signed-in editor
    And the saved text is the spoken words as one paragraph
    And the video is stored as captured in full and no longer needs content
    And one line was printed for each video as it was handled

  Scenario: A video with no captions is recorded so it is not tried again, and stays in To capture with its reason
    Given YouTube has no transcript for the second newest video
    When the transcript worker runs
    Then the second newest video is recorded with the reason "no_transcript"
    And it is not in the list of videos that need content
    And it is still not captured, so the To capture queue lists it with the reason "no_transcript"
    And running the worker again does not ask YouTube about it

  Scenario: A video that cannot be read is reported and the run goes on
    Given YouTube gives an unreadable answer for the newest video
    When the transcript worker runs
    Then the newest video is reported as failed and nothing is saved for it
    And the other videos are still captured
    And the newest video is still waiting for the next run

  Scenario: YouTube blocks this connection, so the worker backs off and stops saying it needs a non-cloud connection
    Given YouTube blocks the request for the second newest video
    When the transcript worker runs
    Then the worker waited and tried that video again before it stopped
    And the videos before it were saved
    And the worker stopped with a message that it needs a non-cloud connection
    And the videos after it were not tried

  Scenario: A dry run lists the videos and contacts neither YouTube nor the save action
    When the transcript worker runs as a dry run
    Then every waiting video was listed
    And YouTube was not asked for anything
    And nothing was saved

  Scenario: The worker can be limited and paced politely
    When the transcript worker runs with a limit of 2 and a pace of 3 seconds
    Then only the 2 newest videos were handled
    And it waited 3 seconds between the requests to YouTube

  Scenario: Without the optional transcript package it says how to install it
    Given the optional transcript package is not installed
    When the transcript worker runs
    Then it stops with a message naming the "transcripts" extra
    And nothing was read from the site

  Scenario: Only a signed-in session is used
    When the transcript worker runs
    Then it used the signed-in client and no AWS credentials
