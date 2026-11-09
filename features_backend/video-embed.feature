@backend @video-embed
Feature: A Story can embed a video as a click-to-play poster
  A news desk editor writes ::video{src="..." title="..." credit="..."} on a line of its own, the way ::image works, to show a video the
  Story is about. The page never loads the player on its own: it holds a poster (a picture in the site's own media storage), a real button
  named by the video's title, and a plain link to the video for readers without JavaScript. Nothing in the static page asks the video
  provider for anything. Only when the reader presses the button does a small script put the provider's player in the poster's place.
  The providers Papyrus knows are a registry kept as data: YouTube, Vimeo and Instagram. A site chooses which of them play with the
  setting embeds.providers, which is empty unless the site lists some. Empty (or no embeds setting at all) is the feature being absent:
  Papyrus does not read ::video, so a site's own hooks see the line exactly as before, and the site publishes exactly the files it did.
  With at least one provider listed, a ::video of a listed provider plays, and a ::video of a known provider that is not listed shows as a
  plain linked credit line. YouTube and Vimeo have a thumbnail that an operator copies into the site's storage; Instagram has none, so its
  ::video names its own poster="..." picture. The Markdown copy keeps the directive exactly as written, so an agent reads the title,
  caption, credit and address from the line itself. In the scenarios below, "embeds off" means no provider is listed. Nothing here
  touches production: the sites, the storage and the video providers are all in memory.

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

  Scenario Outline: Vimeo and Instagram addresses are recognised by the same registry
    When I read the directive with src "<address>" title "A film" and credit "A studio"
    Then the provider is "<provider>" and the video is "<id>"
    And the address of the video on the page is "<watch>"

    Examples:
      | address                                              | provider  | id          | watch                                  |
      | https://vimeo.com/76979871                           | vimeo     | 76979871    | https://vimeo.com/76979871             |
      | https://player.vimeo.com/video/76979871              | vimeo     | 76979871    | https://vimeo.com/76979871             |
      | https://vimeo.com/channels/staffpicks/76979871       | vimeo     | 76979871    | https://vimeo.com/76979871             |
      | https://www.instagram.com/reel/C0abcDEfghI/          | instagram | C0abcDEfghI | https://www.instagram.com/p/C0abcDEfghI/ |
      | https://www.instagram.com/p/C0abcDEfghI/             | instagram | C0abcDEfghI | https://www.instagram.com/p/C0abcDEfghI/ |
      | https://www.instagram.com/example/reel/C0abcDEfghI/  | instagram | C0abcDEfghI | https://www.instagram.com/p/C0abcDEfghI/ |

  Scenario: An address on a video site that is not in the registry is refused and the known providers are named
    When I read the directive with src "https://www.dailymotion.com/video/x7tgad0" title "A film" and credit "A studio"
    Then the directive is refused saying "not an address of a supported video provider"
    And the refusal names the allowed provider "YouTube"
    And the refusal names the allowed provider "Vimeo"
    And the refusal names the allowed provider "Instagram"

  Scenario: An Instagram address with no post in it is refused
    When I read the directive with src "https://www.instagram.com/example/" title "A profile" and credit "Example"
    Then the directive is refused saying "Instagram address without a video in it"

  Scenario: A start time is refused for a provider that cannot start part way through
    When I read the directive with src "https://www.instagram.com/p/C0abcDEfghI/" and these attributes: title="A reel" credit="Example" start="10"
    Then the directive is refused saying "start is not supported for Instagram"

  Scenario: A poster names a picture in the site's own storage
    When I read the directive with src "https://www.instagram.com/p/C0abcDEfghI/" and these attributes: title="A reel" credit="Example" poster="/assets/reel-poster.jpg"
    Then the poster is "/assets/reel-poster.jpg"

  Scenario Outline: A poster that is an address or leaves the storage is refused
    When I read the directive with src "https://www.instagram.com/p/C0abcDEfghI/" and these attributes: title="A reel" credit="Example" poster="<poster>"
    Then the directive is refused saying "poster must be the path of a picture"

    Examples:
      | poster                                  |
      | https://example.org/poster.jpg          |
      | /assets/../secret.jpg                   |
      | javascript:alert(1)                     |
      | /assets/reel-poster.html                |

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
    Then the video save succeeds
    And the stored body data lists the video "UytYrhYLOKI" with its title and credit
    And the save gives no warning about embeds

  Scenario: A Story without a video stores exactly the data it stored before
    When a Story with this body is saved on a site with embeds on:
      """
      Words only.
      """
    Then the video save succeeds
    And the stored body data has no list of videos

  Scenario: A bad directive stops the save and names what to fix
    When a Story with this body is saved on a site with embeds on:
      """
      ::video{src="https://vimeo.com/76979871" credit="A studio"}
      """
    Then the save is refused with the code "video-attrs" saying "needs a title attribute"

  Scenario: Saving a version with credit, caption, start and poster succeeds whatever the site's embeds setting
    When a Story with this body is saved on a site with embeds off:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel" caption="The first pass." start="90" poster="/assets/poster.jpg"}
      """
    Then the video save succeeds
    When a Story with this body is saved on a site with embeds on:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" credit="Example Channel" caption="The first pass." start="90" poster="/assets/poster.jpg"}
      """
    Then the video save succeeds

  Scenario: Embeds off: the line is saved and rendered as before
    When a Story with this body is saved on a site with embeds off:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" poster="/assets/poster.jpg"}
      """
    Then the video save succeeds
    And converting the Markus of that Story gives the same page whether or not it names a credit and a caption

  Scenario: An attribute that is not documented is still refused when embeds are off
    When a Story with this body is saved on a site with embeds off:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration" width="800"}
      """
    Then the save is refused saying "width"

  Scenario: A site with embeds off does not read the directive at all
    When a Story with this body is saved on a site with embeds off:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration"}

      ::video{src="https://www.instagram.com/reel/C0abcDEfghI/" title="A reel from the show"}
      """
    Then the video save succeeds
    And the stored body data has no list of videos

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

  Scenario: A Vimeo video plays from the player address with its start time
    Given a site whose embeds list "vimeo" and that has the poster "vimeo-76979871" in its storage
    When the Story is projected:
      """
      ::video{src="https://vimeo.com/76979871" title="A film" caption="The first pass." credit="A studio" start="90"}
      """
    Then the page has a button named "A film"
    And the poster is the site's own copy under "assets/responsive/assets/video-posters/vimeo-76979871"
    And the player's address is kept as data for the script: "https://player.vimeo.com/video/76979871?autoplay=1&amp;dnt=1#t=90s"
    And the page has no frame
    And the page loads the video script

  Scenario: An Instagram video uses the poster the author names
    Given a site whose embeds list "instagram" and that has the picture "/assets/reel-poster.jpg" in its storage
    When the Story is projected:
      """
      ::video{src="https://www.instagram.com/reel/C0abcDEfghI/" title="A reel from the show" credit="Example Troupe" poster="/assets/reel-poster.jpg"}
      """
    Then the page has a button named "A reel from the show"
    And the poster is the site's own copy under "assets/responsive/assets/reel-poster"
    And the player's address is kept as data for the script: "https://www.instagram.com/p/C0abcDEfghI/embed/"
    And the stock rules give an Instagram player a portrait ratio
    And the page has no frame

  Scenario: An Instagram video with no poster shows the placeholder, because Instagram has no thumbnail to copy
    Given a site whose embeds list "instagram" and that has no pictures in its storage
    When the Story is projected:
      """
      ::video{src="https://www.instagram.com/reel/C0abcDEfghI/" title="A reel from the show" credit="Example Troupe"}
      """
    Then the poster is a placeholder showing the title "A reel from the show"
    And the page has a button named "A reel from the show"

  Scenario: A known provider that the site does not list is a plain linked credit line
    Given a site whose embeds list "youtube" and that has the poster "youtube-UytYrhYLOKI" in its storage
    When the Story is projected:
      """
      ::video{src="https://vimeo.com/76979871" title="A film" caption="The first pass." credit="A studio"}
      """
    Then the page has the line "Video: A film. The first pass. Credit: A studio." with the title linked to "https://vimeo.com/76979871"
    And the page has no button and no frame
    And the page loads no video script

  Scenario Outline: With embeds off the directive is left to Markus and the site's own code
    Given a site with embeds <setting>
    When the Story is projected:
      """
      ::video{src="https://youtu.be/UytYrhYLOKI" title="Aircraft demonstration"}
      """
    Then the page has none of Papyrus's video markup
    And the page has no button and no frame
    And the page loads no video script
    And the site publishes no video script and no content-security-policy fragment

    Examples:
      | setting                              |
      | off                                  |
      | that list no provider                |

  Scenario: A site's own hook still draws its Instagram embed while embeds are off
    Given a site with embeds off and the Pilobolus hook for Instagram lines
    When the Story is projected:
      """
      Opening words.

      ::video{src="https://www.instagram.com/reel/C0abcDEfghI/" title="A reel from the show"}
      """
    Then the page holds the site's own Instagram embed
    And the page has no button and no frame
    And the page loads no video script

  Scenario: A site that lists Instagram moves off its hook, and the same line then needs a credit
    When a Story with this body is saved on a site with embeds on:
      """
      ::video{src="https://www.instagram.com/reel/C0abcDEfghI/" title="A reel from the show"}
      """
    Then the save is refused with the code "video-attrs" saying "needs a credit attribute"

  Scenario: A site that never mentions embeds is the same as one that lists no provider
    Given the same Story on a site with no embeds setting and on a site with embeds that list no provider
    Then the two sites publish identical files

  Scenario: Listing a provider changes no page that has no video
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
      | {"providers": "youtube"}                             | embeds.providers must be a list                      |
      | {"providers": ["dailymotion"]}                       | unsupported provider                                 |
      | {"providers": ["youtube", 3]}                        | embeds.providers must be a list                      |
      | {"enabled": true, "providers": ["youtube"]}          | Unknown embeds settings: enabled                     |
      | {"providers": ["youtube"], "clickToPlay": false}     | a video always loads its player only after a click   |
      | {"providers": ["youtube"], "autoplay": true}         | Unknown embeds settings: autoplay                    |
      | true                                                 | embeds must be an object                             |

  Scenario Outline: The site's content security policy allows the frames of the listed providers and nothing else
    Given a site whose embeds list "<providers>" and that has no pictures in its storage
    When the Story is projected:
      """
      Words only.
      """
    Then the site publishes the policy fragment "<policy>"
    And the fragment allows no script, image, style, connect or default source

    Examples:
      | providers                  | policy                                                                         |
      | youtube                    | frame-src https://www.youtube-nocookie.com                                     |
      | vimeo                      | frame-src https://player.vimeo.com                                             |
      | instagram                  | frame-src https://www.instagram.com                                            |
      | youtube,vimeo,instagram    | frame-src https://www.youtube-nocookie.com https://player.vimeo.com https://www.instagram.com |

  Scenario: The script puts the provider's player in the poster's place on a click, Enter or Space
    When the video script is run against a minimal page
    Then it passes: nothing is framed before a click, a click, Enter and Space each frame the player once, the start time is kept and an address that is not a registered provider's player is refused
    And the script accepts exactly the player addresses of the registry

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
    Then the check P18 needs a look saying "lists no video provider"

  Scenario: A provider the site does not list is called out by the checks
    When the lens checks run on a Story with this body on a site that lists "youtube":
      """
      ::video{src="https://vimeo.com/76979871" title="A film" caption="A caption." credit="A studio"}
      """
    Then the check P18 needs a look saying "plain linked credit line"

  Scenario: An Instagram video with no poster is called out by the checks
    When the lens checks run on a Story with this body on a site that lists "instagram":
      """
      ::video{src="https://www.instagram.com/reel/C0abcDEfghI/" title="A reel" caption="A caption." credit="Example Troupe"}
      """
    Then the check P18 needs a look saying "no poster="

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
    And the picture was stored under "media/assets/video-posters/youtube-UytYrhYLOKI.jpg"
    And the command says it stored the poster

  Scenario: A poster already in storage is not fetched again
    Given a Story whose current text has a video "UytYrhYLOKI" whose poster is already stored
    When I run "stories capture-video-posters" for that Story
    Then the video provider was not asked
    And the command says the poster was already there

  Scenario: A dry run asks nobody and writes nothing
    Given a Story whose current text has a video "UytYrhYLOKI" and YouTube answers with a real thumbnail
    When I run "stories capture-video-posters" for that Story with "--dry-run"
    Then the video provider was not asked
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

  Scenario: A provider with no thumbnail is told to name a poster and is not fetched
    Given a Story whose current text has an Instagram video "C0abcDEfghI" with no poster
    When I run "stories capture-video-posters" for that Story
    Then the video provider was not asked
    And the command says the video needs a poster

  Scenario: A video that names its own poster is not fetched
    Given a Story whose current text has a YouTube video "UytYrhYLOKI" that names its own poster
    When I run "stories capture-video-posters" for that Story
    Then the video provider was not asked
    And the command says the video has its own poster

  Scenario: Directives inside a code fence are documentation and are not fetched
    Given a Story whose current text shows a ::video line only inside a code fence
    When I run "stories capture-video-posters" for that Story
    Then the video provider was not asked
    And the command reports no videos
