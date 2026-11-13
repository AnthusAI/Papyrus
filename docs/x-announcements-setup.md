# Setting up X announcements for your publication

Status: the connection and the settings page are built (epic PPY-09ee86, stories PPY-2deb63 and PPY-ae9d06). Posting itself comes with the announcement backend (PPY-9f4d66); until then you can connect the account, set the rules and see the page, and nothing is posted. This page is written for the site owner, not for developers. Steps 1 to 4 happen on X's website; step 5 is in your newsroom.

When announcements are on, Papyrus posts on your publication's X account each time a Story meets the bar you set (for example, rated 5 stars). Each post carries a short line about the Story and its link. You stay in control: you set the bar, a budget, and a pause switch.

## What you need to know first

- **A paid X subscription is not API access.** The blue check (X Premium) is for your personal use of X. Posting from software uses X's API, which is a separate product with its own prepaid credits.
- **A "developer app" is just a key ring.** On X's developer site you register an "app" that represents your publication's software. X gives it two keys (a client ID and a client secret). Papyrus uses them to ask your permission to post on the account, and X charges that app's credits for each post.
- **Your publication needs its own X account**, the one posts come from. It is an ordinary X account; it does not need a paid subscription. You sign in to X as that account when you connect it in step 5.
- **What it costs** (X's price list, 12 November 2026): a post that contains a link costs $0.20; deleting a post costs $0.01; reading a post costs $0.005. Announcements always contain a link, so budget $0.20 each. $10 covers about 50 announcements.
- **Keys are secrets.** Enter them only in your newsroom's Administration page. Never paste them into chat, email, a document or a ticket. Papyrus stores the secret encrypted and never shows it again.

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

## Step 5: Connect it in the newsroom

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

## How it is kept safe (for operators)

- **Where the keys live.** In AWS Systems Manager Parameter Store as SecureString, under `/papyrus/<site>/announcements/x/` (`<site>` is the site's brand id): `client-secret`, and for the connected account `<accountId>/refresh-token` and `<accountId>/access-token`. They are never in Git, logs, chat or any screen after entry. No operation of the announcements function returns them. Its role may touch only that path.
- **Connecting** uses OAuth 2.0 Authorization Code with PKCE and your app's client secret (a confidential client). The scopes are `tweet.write`, `tweet.read`, `users.read` and `offline.access`; there is no media permission. The PKCE verifier is derived from the client secret and a random value in the `state`, so nothing is stored between leaving for X and coming back, and the verifier never reaches the browser. The page keeps the `state` in the browser's session storage and refuses a return that does not match it; the function refuses a `state` it did not issue.
- **Tokens.** X's access token lasts two hours; the refresh token is single use and rotates. A refresh takes a lease on the connection's row (a DynamoDB conditional write), so two posts at once cause one refresh and both use its token. The new refresh token is saved before the access token is used. The access token is kept in the parameter store too (not only in memory) because the invocations that post cannot share memory.
- **A refresh X refuses** marks the connection "Needs reconnecting" and pauses the site's announcements with the reason "disconnected". Nothing falls back to another account.
- **Disconnect** calls X's `POST /2/oauth2/revoke` and then deletes the parameters, then pauses announcements. If X will not revoke, nothing is deleted and the page says why.
- **Usage.** The page shows X's own post count (`GET /2/usage/tweets`) beside the connection. It is sent with the account's access token; X's documentation does not say whether this endpoint accepts a user token, so the first live check confirms it and the page shows X's message if X refuses.

## Where the settings are stored

One JSON document in the `AnnouncementSettings` model (`id: settings`), the same mechanism as the editorial check settings, written only by the announcements function (`amplify/functions/announcements`), so every rule is enforced there: the mode is Off, Dry run or On (default Off; Dry run and On need a connected account; On also needs the Automated-label confirmation and a budget); the minimum rating is 3, 4 or 5 and never below the three-star quality floor; only Articles and Posts, never References; sections optional; the budget has no default; the price table carries the date it was copied from X's price list. The pause switch (reasons: budget, disconnected, manual) lives in the same document. The X connection (client ID, handle, scopes, refresh health, the lease) is the `XConnection` model's single row; it holds no secret.

The tests are `features_backend/x-account-connection.feature`, `features_backend/announcement-settings.feature` (against a fake X, with no real call), `features/newsroom-announcements.feature` and `scripts/test-announcements.ts` (`npm run test:announcements`).

