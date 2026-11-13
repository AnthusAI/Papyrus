# Setting up X announcements for your publication

Status: the feature is planned, not built (epic PPY-09ee86, plan `docs/plans/scheduled-publishing-and-announcements.md`). This page is written for the site owner, not for developers. Steps 1 to 4 happen on X's website and can be done now; step 5 waits for the feature.

When announcements are on, Papyrus posts on your publication's X account each time a Story meets the bar you set (for example, rated 5 stars). Each post carries a short line about the Story and its link. You stay in control: you set the bar, a budget, and a pause switch.

## What you need to know first

- **A paid X subscription is not API access.** The blue check (X Premium) is for your personal use of X. Posting from software uses X's API, which is a separate product with its own prepaid credits.
- **A "developer app" is just a key ring.** On X's developer site you register an "app" that represents your publication's software. X gives it two keys (a client ID and a client secret). Papyrus uses them to ask your permission to post on the account, and X charges that app's credits for each post.
- **Your publication needs its own X account**, the one posts come from. It is an ordinary X account; it does not need a paid subscription. You sign in to X as that account when you connect it in step 5.
- **What it costs** (X's price list, 12 November 2026): a post that contains a link costs $0.20; deleting a post costs $0.01; reading a post costs $0.005. Announcements always contain a link, so budget $0.20 each. $10 covers about 50 announcements.
- **Keys are secrets.** Enter them only in your newsroom's Administration page. Never paste them into chat, email, a document or a ticket. Papyrus stores them encrypted and never shows them again.

## Step 1: Make sure the publication's X account exists

Sign in to X as the publication's account (or create it). Then mark it as automated, which X's rules ask of accounts that post through software: in that account's settings, find "Your account", then "Automation" (the name may differ), and link it to the person who manages it (your personal account). Its profile will then show an "Automated" label naming you.

## Step 2: Create the developer app

1. Go to developer.x.com and sign in with **your own** account (the person who pays). Open the Developer Console.
2. Accept X's developer terms if asked, and describe the use in plain words, for example: "Posts a short announcement with a link when our publication publishes a new article."
3. Create a new app. Name it after the publication (for example "Machines on Machines announcements").

## Step 3: Set the app's permissions and callback

In the app's settings, find **User authentication settings** and set up OAuth 2.0:

| Setting | Choose |
| --- | --- |
| App permissions | Read and write |
| Type of app | Web App, Automated App or Bot (this is the "confidential client" type, which gets a client secret) |
| Callback URI / Redirect URL | Copy it exactly from your newsroom's Administration > Announcements page. It looks like `https://<your site>/newsroom/settings/announcements/x/callback` |
| Website URL | Your publication's home page |

Save. X then shows the **OAuth 2.0 Client ID** and **Client Secret**. Keep this tab open; you need them in step 5. If you lose the secret, X lets you make a new one ("regenerate"); you then replace it in step 5.

You do not need the older "API key", "API secret", "Bearer token" or "Access token" values; Papyrus does not use them.

## Step 4: Buy credits and set a spending limit

1. In the Developer Console, open billing, add a card, and buy credits (for example $10).
2. Set a **spending limit** per billing cycle equal to the budget you will enter in Papyrus (for example $10). X stops requests at that limit, so this is a second guard beside Papyrus's own budget.
3. Leave auto-recharge off unless you want X to top up the balance on its own.

## Step 5: Connect it in the newsroom (when the feature ships)

1. Open your newsroom, then **Administration > Announcements**.
2. Under **X app**, paste the Client ID and the Client Secret, and save. The page then says "Secret saved"; it never shows the secret again.
3. Choose **Connect X account**. X opens; make sure you are signed in as the **publication's** account (not your personal one), and approve. You return to the newsroom, which says "Connected: @handle".
4. Set the rules: which Stories are announced (Articles, Posts, sections) and the minimum star rating. Enter your **budget per X billing cycle** (the same as X's spending limit).
5. Tick "This account shows X's Automated label, managed by a person's account".
6. Set **Mode** to **Dry run** first. Papyrus builds each announcement exactly as it would post it and shows it to you, without sending anything or spending anything.
7. When the dry runs look right, set Mode to **On**. Watch the first live post; the **Pause** switch and **Withdraw announcement** (deletes the post) are on the same page.

## Later

- **Pause** stops all posting at once. Papyrus also pauses on its own when the budget is reached or the connection breaks, and says why.
- **Disconnect** removes Papyrus's permission at X and deletes the stored token.
- **Replace secret** if you regenerate the secret at X.

## Text shown in the newsroom (Administration > Announcements)

The product shows these steps in short form beside the settings:

> **Announce new Stories on X.** Papyrus posts on your publication's X account when a Story meets the bar you set. You need an X developer app (a paid X subscription does not include this) with prepaid credits; each announcement costs about $0.20.
>
> 1. On developer.x.com, create an app for this publication.
> 2. In its User authentication settings choose OAuth 2.0, "Read and write", "Web App, Automated App or Bot", and paste this callback URL: `{callbackUrl}` [Copy].
> 3. Buy credits and set a spending limit equal to your budget below.
> 4. Paste the app's Client ID and Client Secret here. We store the secret encrypted and never show it again.
> 5. Choose "Connect X account" and sign in as the publication's account.
> 6. Start in "Dry run" to see posts without sending them; switch to "On" when they look right.
>
> Full guide: [Setting up X announcements].
