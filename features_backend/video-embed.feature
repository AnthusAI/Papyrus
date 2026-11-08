@backend @video-embed
Feature: A Story can embed a YouTube video as a click-to-play poster
  A news desk editor writes ::video{src="..." title="..." credit="..."} on a line of its own, the way ::image works, to show a video the
  Story is about. The page never loads the player on its own: it holds a poster (our own copy of the video's thumbnail, kept in the site's
  media storage), a real button named by the video's title, and a plain link to the video for readers without JavaScript. Nothing in the
  static page asks YouTube or Google for anything. Only when the reader presses the button does a small script put the privacy-enhanced
  player in the poster's place. A site chooses whether videos play at all with the setting "embeds" (off unless the site turns it on);
  with it off a ::video is a plain line with the title, the credit and the link. The Markdown copy keeps the directive exactly as written,
  so an agent reads the title, caption, credit and address from the line itself. Nothing here touches production: the sites, the storage and
  YouTube are all in memory.

  Scenario Outline: Every YouTube address shape names the same video
    When I read the directive with src "<address>" title "Aircraft demonstration" and credit "Example Channel"
    Then the video is "UytYrhYLOKI"
    And the address of the video on the page is "https://www.youtube.com/watch?v=UytYrhYLOKI"

    Examples:
      | address                                              |
      | https://www.youtube.com/watch?v=UytYrhYLOKI          |
      | https://youtu.be/UytYrhYLOKI                         |
      | https://www.youtube.com/shorts/UytYrhYLOKI           |
      | https://www.youtube.com/live/UytYrhYLOKI             |
      | https://www.youtube.com/embed/UytYrhYLOKI            |
      | https://m.youtube.com/watch?v=UytYrhYLOKI&feature=x  |

  Scenario: An address on another video site is refused and the allowed providers are named
    When I read the directive with src "https://vimeo.com/76979871" title "A film" and credit "A studio"
    Then the directive is refused saying "not an address of a supported video provider"
    And the refusal names the allowed provider "YouTube"

  Scenario: A YouTube address with no video in it is refused
    When I read the directive with src "https://www.youtube.com/@examplechannel" title "A channel" and credit "A channel"
    Then the directive is refused saying "without a video in it"

  Scenario: An address that is not a web address is refused
    When I read the directive with src "javascript:alert(1)" title "A film" and credit "A studio"
    Then the directive is refused saying "not an address of a supported video provider"

  Scenario Outline: The title and the credit are required
    When I read the directive with src "https://youtu.be/UytYrhYLOKI" and these attributes: <attributes>
    Then the directive is refused saying "<message>"

    Examples:
      | attributes                      | message                                                      |
      | credit="Example Channel"        | needs a title attribute: the accessible name of the player   |
      | title="Aircraft demonstration"  | needs a credit attribute: the channel or person              |
      | title="  " credit="Example"     | needs a title attribute                                      |
      | title="A film" credit=""        | needs a credit attribute                                     |

  Scenario: The address is required
    When I read the directive with these attributes only: title="A film" credit="A studio"
    Then the directive is refused saying "needs a src attribute"

  Scenario: The caption, the start time and the layout are optional with plain defaults
    When I read the directive with src "https://youtu.be/UytYrhYLOKI" title "A film" and credit "A studio"
    Then the layout is "inline" and there is no caption and no start time

  Scenario: A start time and the full layout are read
    When I read the directive with src "https://youtu.be/UytYrhYLOKI" and these attributes: title="A film" credit="A studio" caption="The first pass." start="90" layout="full"
    Then the start time is 90 seconds and the layout is "full" and the caption is "The first pass."

  Scenario Outline: A start time or layout that does not make sense is refused
    When I read the directive with src "https://youtu.be/UytYrhYLOKI" and these attributes: title="A film" credit="A studio" <attribute>
    Then the directive is refused saying "<message>"

    Examples:
      | attribute         | message                                  |
      | start="1:30"      | start must be whole seconds              |
      | start="-5"        | start must be whole seconds              |
      | layout="right"    | layout must be one of inline, full       |
      | width="800"       | unknown attribute(s) width               |

  Scenario: A Story with a video is saved and the video is kept in the stored body
    When a Story with this body is saved on a site with embeds on:
      """
      Words before.

      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel"}

      Words after.
      """
    Then the save succeeds
    And the stored body data lists the video "UytYrhYLOKI" with its title and credit
    And the save gives no warning about embeds

  Scenario: A Story without a video stores exactly the data it stored before
    When a Story with this body is saved on a site with embeds on:
      """
      Words only.
      """
    Then the save succeeds
    And the stored body data has no list of videos

  Scenario: A bad directive stops the save and names what to fix
    When a Story with this body is saved on a site with embeds on:
      """
      ::video{src="https://vimeo.com/76979871" title="A film" credit="A studio"}
      """
    Then the save is refused with the code "video-attrs" saying "Allowed providers"

  Scenario: A site with embeds off still accepts the video and says it will show a link
    When a Story with this body is saved on a site with embeds off:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel"}
      """
    Then the save succeeds
    And the save warns "video embeds off"

  Scenario: With embeds on, the page holds a poster, a button and a plain link, and the player waits for a click
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="Two microphones, one jet." credit="Example Channel" start="90"}
      """
    Then the page has a button named "Aircraft demonstration"
    And the button holds the Lucide play icon as a flat filled shape
    And the poster is the site's own copy under "assets/responsive/assets/video-posters/"
    And the poster is a plain link to "https://www.youtube.com/watch?v=UytYrhYLOKI&amp;t=90s" with the title as its text
    And the figure caption reads "Two microphones, one jet." and credits "Example Channel" with a link to the video
    And the page has no frame
    And the player's address is kept as data for the script: the privacy-enhanced address with autoplay, the start time 90 and no related videos
    And the page loads the video script

  Scenario: Nothing in the static page asks YouTube or Google for anything
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}
      """
    Then the page mentions no picture host, no frame and no stream host of the video provider
    And the only provider addresses in the page are the plain links to the video and the player address kept as data for the script
    And no image, script, stylesheet or link-preload address in the page is on the video provider

  Scenario: The poster is shaped by the design system and works for dark mode and keyboards
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel"}
      """
    Then the stock rules use the media ratio token with 16 by 9 as its fallback
    And the stock rules draw the button as a flat shape with no border and colours from the site's tokens
    And the button is a real button element and the poster link is hidden once the script has made the button available

  Scenario: A video whose poster has not been copied yet shows the placeholder with its title
    Given a site with embeds on that has no poster for "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel"}
      """
    Then the poster is a placeholder showing the title "Aircraft demonstration"
    And the page mentions no picture host, no frame and no stream host of the video provider
    And the page has a button named "Aircraft demonstration"

  Scenario: The full layout is the image layout class
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel" layout="full"}
      """
    Then the figure has the classes "papyrus-image papyrus-image--full papyrus-video"

  Scenario: Two videos on a page share one set of rules and one script
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="First" credit="Example Channel"}

      ::video{src="https://youtu.be/UytYrhYLOKI" title="Second" credit="Example Channel"}
      """
    Then the page has 2 buttons and the stock rules once and the video script once

  Scenario: With embeds off a video is the plain line and never a player
    Given a site with embeds off
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="Two microphones, one jet." credit="Example Channel"}
      """
    Then the page has the line "Video: Aircraft demonstration. Two microphones, one jet. Credit: Example Channel." with the title linked to the video
    And the page has no button and no frame
    And the page loads no video script
    And the site publishes no video script and no content-security-policy fragment

  Scenario: A site that never mentions embeds is the same as one that turns them off
    Given the same Story on a site with no embeds setting and on a site with embeds off
    Then the two sites publish identical files

  Scenario: Turning embeds on changes no page that has no video
    Given the same Story without a video on a site with embeds off and on a site with embeds on
    Then every page of the two sites is identical
    And the site with embeds on publishes two more files: the video script and the content-security-policy fragment

  Scenario: The Markdown copy keeps the directive exactly as written
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="Two microphones, one jet." credit="Example Channel"}
      """
    Then the Markdown copy holds the line exactly as written, with the title, caption, credit and address in it

  Scenario Outline: The settings are read as data and wrong ones are refused in plain words
    Then the setting <setting> is refused saying "<message>"

    Examples:
      | setting                                              | message                                              |
      | {"enabled": "yes"}                                   | embeds.enabled must be true or false                 |
      | {"enabled": true, "providers": ["vimeo"]}            | unsupported provider                                 |
      | {"enabled": true, "providers": []}                   | non-empty list of provider names                     |
      | {"enabled": true, "clickToPlay": false}              | a video always loads its player only after a click   |
      | {"enabled": true, "autoplay": true}                  | Unknown embeds settings: autoplay                    |
      | true                                                 | embeds must be an object                             |

  Scenario: The site's content security policy allows the player's frame and nothing else
    Given a site with embeds on that has the poster of "UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      Words only.
      """
    Then the site publishes the policy fragment "frame-src https://www.youtube-nocookie.com"
    And the fragment allows no script, image, style, connect or default source

  Scenario: The script puts the privacy-enhanced player in the poster's place on a click, Enter or Space
    When the video script is run against a minimal page
    Then it passes: nothing is framed before a click, a click, Enter and Space each frame the player once, the start time is kept and an address that is not the privacy-enhanced player is refused

  Scenario: A story's video titles and credits are checked in plain words
    When the lens checks run on a Story with this body:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel"}
      """
    Then the check P16 looks fine
    And the check P17 needs a look saying "no caption"

  Scenario: A video with no title or no credit is a problem that blocks the step
    When the lens checks run on a Story with this body:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" caption="A caption."}
      """
    Then the check P16 is a problem saying "no title and no credit"
    And the check P10 is a problem saying "third-party picture with no credit"

  Scenario: The poster counts as a third-party picture that is credited
    When the lens checks run on a Story with this body:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}
      """
    Then the check P10 looks fine saying "Every third-party picture is credited"

  Scenario: A site with embeds off is told so by the checks
    When the lens checks run on a Story with this body on a site with embeds off:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}
      """
    Then the check P18 needs a look saying "video embeds off"

  Scenario: A site with embeds on passes the embeds check
    When the lens checks run on a Story with this body on a site with embeds on:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}
      """
    Then the check P18 looks fine

  Scenario: A credited video that is not among the citations is flagged
    When the lens checks run on a Story with this body:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}
      """
    Then the check A15 needs a look saying "not among the Story's citations"

  Scenario: A credited video that is cited passes
    When the lens checks run on a Story that cites the video "https://www.youtube.com/watch?v=UytYrhYLOKI" with this body:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}

      The demonstration shows the method [@demo].
      """
    Then the check A15 looks fine

  Scenario: A Story with a video still passes the image, citation and Markdown-copy checks
    When the lens checks run on a Story that cites the video "https://www.youtube.com/watch?v=UytYrhYLOKI" with this body on a site with embeds on:
      """
      ::image{src="/assets/own.jpg" alt="A harbour at dawn" credit="Image: A, CC0"}

      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" caption="A caption." credit="Example Channel"}

      The demonstration shows the method [@demo].

      ::citations{}
      """
    Then the checks P7, P8, P10, A2, A5, A10 and P16 all look fine

  Scenario: A story with no video has nothing to check about videos
    When the lens checks run on a Story with this body:
      """
      Words only.
      """
    Then the checks P16, P17, P18 and A15 do not apply

  Scenario: The poster is copied into the site's storage where the page reads it
    Given a Story whose current text has a video "UytYrhYLOKI" and YouTube answers with a real thumbnail
    When I run "stories capture-video-posters" for that Story
    Then the thumbnail was asked for at "https://img.youtube.com/vi/UytYrhYLOKI/hqdefault.jpg"
    And the picture was stored under "media/assets/video-posters/UytYrhYLOKI.jpg"
    And the command says it stored the poster

  Scenario: A poster already in storage is not fetched again
    Given a Story whose current text has a video "UytYrhYLOKI" whose poster is already stored
    When I run "stories capture-video-posters" for that Story
    Then YouTube was not asked
    And the command says the poster was already there

  Scenario: A dry run asks nobody and writes nothing
    Given a Story whose current text has a video "UytYrhYLOKI" and YouTube answers with a real thumbnail
    When I run "stories capture-video-posters" for that Story with "--dry-run"
    Then YouTube was not asked
    And nothing was stored
    And the command says it would fetch the poster

  Scenario: YouTube's grey stand-in for a missing thumbnail is never stored
    Given a Story whose current text has a video "UytYrhYLOKI" and YouTube answers with a grey stand-in
    When I run "stories capture-video-posters" for that Story
    Then nothing was stored
    And the command says there is no poster for the video

  Scenario: A connection YouTube refuses stops the run after three refusals
    Given a Story whose current text has 4 different videos and YouTube refuses this connection
    When I run "stories capture-video-posters" for that Story
    Then the command stopped with status 3 after 3 refusals
    And nothing was stored

  Scenario: Directives inside a code fence are documentation and are not fetched
    Given a Story whose current text shows a ::video line only inside a code fence
    When I run "stories capture-video-posters" for that Story
    Then YouTube was not asked
    And the command reports no videos
