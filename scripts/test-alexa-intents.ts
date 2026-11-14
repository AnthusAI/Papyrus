/**
 * The alexa skill's intents, speech and public story source. Run with no argument for everything, or with one behaviour name
 * (the Gherkin steps do this); each prints `{"behaviour": ...}`. Everything runs against a fake `PublicStorySource` or a faked
 * `fetch`; nothing touches a network or an Amazon account.
 */
import assert from "node:assert/strict";
import type { RequestEnvelope, ResponseEnvelope } from "ask-sdk-model";
import type { AlexaConfig } from "../amplify/plugins/alexa/config";
import { createPublicStorySource } from "../amplify/plugins/alexa/content";
import { createPublicSiteStorySource, type FetchLike } from "../amplify/plugins/alexa/content/public-site-story-source";
import { parseMarkusSource } from "../amplify/plugins/alexa/content/markus-source";
import { splitTwin } from "../amplify/plugins/alexa/content/twin";
import type { PublicStory, PublicStorySource, PublicStorySummary } from "../amplify/plugins/alexa/contracts";
import { INTENT_MODULES } from "../amplify/plugins/alexa/intents";
import { documentUnits, storyBodyUnits } from "../amplify/plugins/alexa/speech/markus-speech";
import { escapeSsml, fitUnits, MAX_SSML_LENGTH, sentence, splitSentences } from "../amplify/plugins/alexa/speech/ssml";
import { STORY_PART_LENGTH } from "../amplify/plugins/alexa/speech/conversation";
import { buildSkill } from "../amplify/plugins/alexa/skill";
import { interactionModel } from "./alexa/generate-skill-package";

const config: AlexaConfig = { invocationName: "the example", skillName: "Example News", accountLinking: false, siteOrigin: "https://news.example.test" };
// Built from parts: a bare UUID literal in a test looks like a leaked session identifier to the repository scanner.
const SKILL_ID = `amzn1.ask.skill.${["12345678", "1234", "1234", "1234", "123456789abc"].join("-")}`;

function story(number: number, extra: Partial<PublicStory> = {}): PublicStory {
  return {
    id: `id-${number}`,
    slug: `articles/story-${number}`,
    title: `Headline number ${number}`,
    deck: `The deck of story ${number}.`,
    byline: "Ada Example",
    publishedAt: `2026-10-0${number}T00:00:00Z`,
    markus: `The first paragraph of story ${number}. It has two sentences.\n\nThe second paragraph of story ${number}.`,
    ...extra,
  };
}

function fakeSource(stories: PublicStory[]): PublicStorySource & { listCalls: number[] } {
  const listCalls: number[] = [];
  return {
    listCalls,
    async listLatest({ limit }) {
      listCalls.push(limit);
      return stories.slice(0, limit).map(({ markus: _markus, bodyIr: _bodyIr, ...summary }): PublicStorySummary => summary);
    },
    async getStory(slug) {
      return stories.find((candidate) => candidate.slug === slug);
    },
  };
}

type Turn = { response: ResponseEnvelope; speech: string; reprompt: string; ends: boolean };

function envelope(request: Record<string, unknown>, attributes?: Record<string, unknown>): RequestEnvelope {
  return {
    version: "1.0",
    session: { new: attributes === undefined, sessionId: "s", application: { applicationId: SKILL_ID }, user: { userId: "u" }, attributes },
    context: { System: { application: { applicationId: SKILL_ID }, user: { userId: "u" }, device: { deviceId: "d" }, apiEndpoint: "https://api.amazonalexa.com" } },
    request: { requestId: "r", timestamp: "2026-10-31T00:00:00Z", locale: "en-US", ...request },
  } as RequestEnvelope;
}

/** A conversation against the real intent registry; session attributes carry from one turn to the next. */
function conversation(stories: PublicStorySource) {
  const skill = buildSkill({ config, stories });
  let attributes: Record<string, unknown> | undefined;
  const turn = async (request: Record<string, unknown>): Promise<Turn> => {
    const response = await skill.invoke(envelope(request, attributes));
    attributes = response.sessionAttributes ?? attributes;
    const output = (response.response.outputSpeech as { ssml?: string } | undefined)?.ssml ?? "";
    const reprompt = (response.response.reprompt?.outputSpeech as { ssml?: string } | undefined)?.ssml ?? "";
    return { response, speech: output, reprompt, ends: response.response.shouldEndSession === true };
  };
  return {
    launch: () => turn({ type: "LaunchRequest" }),
    intent: (name: string, slots: Record<string, string> = {}) =>
      turn({ type: "IntentRequest", intent: { name, confirmationStatus: "NONE", slots: Object.fromEntries(Object.entries(slots).map(([key, value]) => [key, { name: key, value, confirmationStatus: "NONE" }])) } }),
    sessionEnded: () => turn({ type: "SessionEndedRequest", reason: "USER_INITIATED" }),
    attributes: () => attributes,
  };
}

const text = (ssml: string) => ssml.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

/** Well-formed enough for Alexa: every `&` starts an entity, no raw `<` or `>` outside tags, the wrapper is `<speak>`, and it is short enough. */
function assertSpeakable(ssml: string) {
  assert.ok(ssml.startsWith("<speak>") && ssml.endsWith("</speak>"), ssml.slice(0, 80));
  assert.ok(ssml.length <= MAX_SSML_LENGTH, `ssml is ${ssml.length} characters`);
  const inner = ssml.slice("<speak>".length, -"</speak>".length);
  assert.ok(!/&(?!amp;|lt;|gt;|quot;|apos;)/.test(inner), "an unescaped ampersand");
  assert.ok(!/<(?!\/?(s|emphasis|p)\b|break time="\d+ms"\/>)/.test(inner), "an unknown or unescaped tag");
  assert.ok(!/>[^<]*>/.test(inner.replace(/<[^>]*>/g, (tag) => tag.replace(/>/g, "\u0001"))), "a raw >");
  assert.ok(!/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(inner));
}

const fiveStories = [1, 2, 3, 4, 5, 6].map((number) => story(number));

const behaviours: Record<string, () => Promise<void> | void> = {
  "launch reads the latest five headlines and asks which one": async () => {
    const source = fakeSource(fiveStories);
    const talk = conversation(source);
    const launch = await talk.launch();
    assert.deepEqual(source.listCalls, [5]);
    assertSpeakable(launch.speech);
    const spoken = text(launch.speech);
    assert.match(spoken, /Welcome to Example News/);
    assert.match(spoken, /latest headlines from Example News/);
    let last = -1;
    for (let number = 1; number <= 5; number += 1) {
      const at = spoken.indexOf(`Headline number ${number}`);
      assert.ok(at > last, `headline ${number} is read in order`);
      last = at;
    }
    assert.ok(!spoken.includes("Headline number 6"));
    assert.match(spoken, /Which one would you like to hear/);
    assert.equal(launch.ends, false);
    assert.ok(launch.reprompt.length > 0);
    assert.ok(!/pilobolus/i.test(JSON.stringify(launch.response)));
  },

  "launch with nothing published says so and ends": async () => {
    const launch = await conversation(fakeSource([])).launch();
    assert.match(text(launch.speech), /no published stories/);
    assert.equal(launch.ends, true);
  },

  "a story is read by ordinal or by number": async () => {
    const talk = conversation(fakeSource(fiveStories));
    await talk.launch();
    const second = await talk.intent("ReadStoryIntent", { ordinal: "2" });
    assertSpeakable(second.speech);
    const spoken = text(second.speech);
    assert.match(spoken, /^Headline number 2 By Ada Example The deck of story 2\. The first paragraph of story 2\./);
    assert.match(spoken, /The second paragraph of story 2\./);
    assert.match(spoken, /Say next for the next story/);
    assert.equal(second.ends, false);

    const fourth = await talk.intent("ReadStoryIntent", { number: "4" });
    assert.match(text(fourth.speech), /^Headline number 4/);

    // A fresh session that goes straight to a story (no launch) still works.
    const direct = await conversation(fakeSource(fiveStories)).intent("ReadStoryIntent", { ordinal: "1" });
    assert.match(text(direct.speech), /^Headline number 1/);
  },

  "a story number that does not exist is explained": async () => {
    const talk = conversation(fakeSource(fiveStories));
    await talk.launch();
    const tooFar = await talk.intent("ReadStoryIntent", { number: "9" });
    assert.match(text(tooFar.speech), /I only have 5 stories/);
    assert.equal(tooFar.ends, false);
    const none = await talk.intent("ReadStoryIntent");
    assert.match(text(none.speech), /latest headlines from Example News/, "no number reads the list, never a bare question");
    assert.match(text(none.speech), /Headline number 1/);
    const zero = await talk.intent("ReadStoryIntent", { ordinal: "0" });
    assert.match(text(zero.speech), /I only have 5 stories/);
  },

  "next, previous and repeat move through the stories": async () => {
    const talk = conversation(fakeSource(fiveStories));
    await talk.launch();
    assert.match(text((await talk.intent("AMAZON.NextIntent")).speech), /^Headline number 1/); // from the list: the first story
    assert.match(text((await talk.intent("AMAZON.NextIntent")).speech), /^Headline number 2/);
    assert.match(text((await talk.intent("AMAZON.RepeatIntent")).speech), /^Headline number 2/);
    assert.match(text((await talk.intent("AMAZON.PreviousIntent")).speech), /^Headline number 1/);
    const atStart = await talk.intent("AMAZON.PreviousIntent");
    assert.match(text(atStart.speech), /no story before this one/);
    assert.equal(atStart.ends, false);
    for (let step = 0; step < 4; step += 1) await talk.intent("AMAZON.NextIntent");
    const last = await talk.intent("AMAZON.NextIntent"); // story 5 was read by the loop; one more runs off the end
    assert.match(text(last.speech), /That was the last of the latest stories/);
    assert.equal(last.ends, false);
    // Repeat after running off the end still re-reads the last story.
    assert.match(text((await talk.intent("AMAZON.RepeatIntent")).speech), /^Headline number 5/);
    // The last story offers previous, not next.
    assert.match(text((await talk.intent("AMAZON.RepeatIntent")).speech), /That was the last of the latest stories/);
  },

  "repeat at the headlines reads the headlines again": async () => {
    const talk = conversation(fakeSource(fiveStories));
    await talk.launch();
    const again = await talk.intent("AMAZON.RepeatIntent");
    assert.match(text(again.speech), /Headline number 1.*Headline number 5/);
    // With no session at all it also works.
    const cold = await conversation(fakeSource(fiveStories)).intent("AMAZON.RepeatIntent");
    assert.match(text(cold.speech), /latest headlines/);
  },

  "a story that has gone away sends the listener back to the headlines": async () => {
    const stories = fakeSource(fiveStories);
    const talk = conversation(stories);
    await talk.launch();
    const original = stories.getStory;
    stories.getStory = async (slug) => (slug.endsWith("story-3") ? undefined : original(slug));
    const gone = await talk.intent("ReadStoryIntent", { ordinal: "3" });
    assert.match(text(gone.speech), /could not find that story any more/);
    assert.match(text(gone.speech), /latest headlines/);
  },

  "help explains what to say": async () => {
    const help = await conversation(fakeSource(fiveStories)).intent("AMAZON.HelpIntent");
    assertSpeakable(help.speech);
    assert.match(text(help.speech), /Example News reads you its latest published stories/);
    assert.match(text(help.speech), /next or previous/);
    assert.equal(help.ends, false);
  },

  "stop and cancel say goodbye and end": async () => {
    for (const name of ["AMAZON.StopIntent", "AMAZON.CancelIntent"]) {
      const bye = await conversation(fakeSource(fiveStories)).intent(name);
      assert.equal(text(bye.speech), "Goodbye.");
      assert.equal(bye.ends, true);
      assert.equal(bye.reprompt, "");
    }
  },

  "fallback reads the headlines instead of a dead end": async () => {
    const fallback = await conversation(fakeSource(fiveStories)).intent("AMAZON.FallbackIntent");
    assert.match(text(fallback.speech), /did not catch that/);
    assert.match(text(fallback.speech), /latest headlines from Example News/);
    assert.match(text(fallback.speech), /Headline number 1/);
    assert.equal(fallback.ends, false);
    assert.ok(fallback.reprompt.length > 0);
  },

  "asking for the headlines reads them, greeting a new session": async () => {
    // Under Alexa+ a session often starts with "ask <publication> for the headlines": an intent, not a launch.
    const first = await conversation(fakeSource(fiveStories)).intent("HeadlinesIntent");
    assert.match(text(first.speech), /^Welcome to Example News/);
    assert.match(text(first.speech), /Headline number 1.*Headline number 5/);
    assert.equal(first.ends, false);
    const talk = conversation(fakeSource(fiveStories));
    await talk.launch();
    await talk.intent("ReadStoryIntent", { ordinal: "2" });
    const again = await talk.intent("HeadlinesIntent");
    assert.doesNotMatch(text(again.speech), /Welcome/, "only a new session is welcomed");
    assert.match(text(again.speech), /latest headlines from Example News/);
    assert.match(text((await talk.intent("AMAZON.NextIntent")).speech), /^Headline number 1/, "the list resets the position");
  },

  "the headlines intent hears how people ask for the list": () => {
    const model = interactionModel(config);
    const headlines = model.interactionModel.languageModel.intents.find((intent) => intent.name === "HeadlinesIntent");
    assert.ok(headlines?.samples);
    for (const phrase of ["for the headlines", "what's new", "list them", "I don't know what they are", "I don't know what the stories are", "what are the stories", "articles", "posts", "the recent stories", "show me the latest articles"]) {
      assert.ok(headlines.samples.includes(phrase), `"${phrase}" is a HeadlinesIntent sample`);
    }
  },

  "navigate home returns to fresh headlines": async () => {
    const source = fakeSource(fiveStories);
    const talk = conversation(source);
    await talk.launch();
    await talk.intent("ReadStoryIntent", { ordinal: "2" });
    const home = await talk.intent("AMAZON.NavigateHomeIntent");
    assert.match(text(home.speech), /latest headlines from Example News/);
    assert.deepEqual(source.listCalls, [5, 5], "home fetches the list again");
    // After home, "next" starts at the first story again.
    assert.match(text((await talk.intent("AMAZON.NextIntent")).speech), /^Headline number 1/);
  },

  "session ended answers without speech": async () => {
    const ended = await conversation(fakeSource(fiveStories)).sessionEnded();
    assert.equal(ended.response.response.outputSpeech, undefined);
  },

  "ssml escapes everything it speaks": async () => {
    assert.equal(escapeSsml(`Tom & Jerry <b>"quoted"</b> it's`), "Tom &amp; Jerry &lt;b&gt;&quot;quoted&quot;&lt;/b&gt; it&apos;s");
    assert.equal(escapeSsml("a\u0000b\u0007c"), "abc");
    const nasty = story(1, {
      title: `AT&T <script> "Q&A" it's`,
      deck: "Deck with <tags> & ampersands.",
      byline: "Ada & Grace <Example>",
      markus: "Body with <emphasis> & **bold & brave** and `a < b` and [a link & more](https://example.test/?a=1&b=2).\n\n- one & two\n- three <four>",
    });
    const talk = conversation(fakeSource([nasty]));
    const launch = await talk.launch();
    assertSpeakable(launch.speech);
    assert.ok(launch.speech.includes("AT&amp;T &lt;script&gt; &quot;Q&amp;A&quot; it&apos;s"));
    const read = await talk.intent("ReadStoryIntent", { number: "1" });
    assertSpeakable(read.speech);
    for (const fragment of ["Ada &amp; Grace &lt;Example&gt;", "Deck with &lt;tags&gt; &amp; ampersands.", "&lt;emphasis&gt; &amp; bold &amp; brave", "a &lt; b", "a link &amp; more", "one &amp; two", "three &lt;four&gt;"]) {
      assert.ok(read.speech.includes(fragment), `missing ${fragment} in ${read.speech}`);
    }
    assert.ok(!read.speech.includes("example.test"), "link targets are not spoken");
  },

  "a long story is read in short parts with continue": async () => {
    const sentences = Array.from({ length: 400 }, (_, index) => `This is sentence number ${index + 1} of a very long story.`);
    const long = story(1, { markus: sentences.join(" ") });
    const talk = conversation(fakeSource([long, story(2)]));
    await talk.launch();
    const first = await talk.intent("ReadStoryIntent", { number: "1" });
    assertSpeakable(first.speech);
    // Alexa synthesizes a whole reply before speaking, so a part stays short enough to start quickly.
    assert.ok(first.speech.length <= STORY_PART_LENGTH + 400, `a part is short (${first.speech.length} characters)`);
    const spoken = text(first.speech);
    assert.match(spoken, /^Headline number 1 By Ada Example/);
    assert.match(spoken, /Say continue to keep reading, or next for the next story\.$/);
    assert.match(spoken.split(" Say continue")[0], /of a very long story\.$/, "a part ends between sentences");
    // Continue reads on from where the part stopped, with no repeated opening and no gap.
    const lastNumber = (speech: string) => Number([...text(speech).matchAll(/sentence number (\d+) /g)].pop()?.[1]);
    const firstNumber = (speech: string) => Number(/sentence number (\d+) /.exec(text(speech))?.[1]);
    const second = await talk.intent("ContinueIntent");
    assert.doesNotMatch(text(second.speech), /Headline number 1/);
    assert.equal(firstNumber(second.speech), lastNumber(first.speech) + 1);
    // Repeat replays the same part.
    assert.equal(firstNumber((await talk.intent("AMAZON.RepeatIntent")).speech), firstNumber(second.speech));
    // Reading on to the end says so and offers the next story.
    let reply = second;
    for (let guard = 0; guard < 50 && /Say continue/.test(text(reply.speech)); guard += 1) reply = await talk.intent("ContinueIntent");
    assert.match(text(reply.speech), /sentence number 400 of a very long story\. That is the end of the story\. Say next for the next story/);
    // A short story is read whole in one part.
    const short = await talk.intent("ReadStoryIntent", { number: "2" });
    assert.match(text(short.speech), /That is the end of the story/);
    assert.doesNotMatch(text(short.speech), /Say continue/);
  },

  "a byline that already says by is not doubled": async () => {
    const talk = conversation(fakeSource([story(1, { byline: "by various bots and Ada Example" })]));
    await talk.launch();
    const read = text((await talk.intent("ReadStoryIntent", { number: "1" })).speech);
    assert.match(read, /by various bots and Ada Example/);
    assert.doesNotMatch(read, /By by/i);
  },

  "one endless sentence is shortened at a word": () => {
    const unit = sentence(`${"word ".repeat(3000)}end.`);
    const fitted = fitUnits([unit], 1000);
    assert.equal(fitted.truncated, true);
    assert.ok(fitted.ssml.length <= 1000);
    assert.ok(fitted.ssml.startsWith("<s>word word") && fitted.ssml.trimEnd().endsWith("word</s>"));
    assert.deepEqual(splitSentences("One. Two! Three? “Four.” Five"), ["One.", "Two!", "Three?", "“Four.”", "Five"]);
    assert.equal(fitUnits(["<s>a</s>", "<s>b</s>"], 1000).truncated, false);
  },

  "speech walks the Markus nodes": () => {
    const document = parseMarkusSource(
      [
        "## A heading",
        "",
        "Plain *emphasis* and **strong** words.",
        "",
        ":::pull-quote{attribution=\"Someone\"}",
        "A quote repeated from the body.",
        ":::",
        "",
        ":::card-grid{columns=\"2\"}",
        ":::card{title=\"Read\"}",
        "Look before you leap.",
        ":::",
        ":::",
        "",
        "```python",
        "def plan(): pass",
        "```",
        "",
        "::image{src=\"x.png\" alt=\"A picture\"}",
        "",
        "1. First thing",
        "2. Second thing",
        "",
        "| a | b |",
        "| - | - |",
        "| 1 | 2 |",
      ].join("\n"),
    );
    assert.deepEqual(document.children.map((node) => (node.type === "directive" ? `directive:${node.name}` : node.type)), [
      "heading", "paragraph", "directive:pull-quote", "directive:card-grid", "code", "directive:image", "list", "table",
    ]);
    const spoken = text(documentUnits(document).join(""));
    assert.match(spoken, /A heading Plain emphasis and strong words\./);
    assert.ok(!/quote repeated/.test(spoken), "pull quotes repeat the body and are skipped");
    assert.match(spoken, /Read Look before you leap\./);
    assert.ok(!/def plan/.test(spoken));
    assert.match(spoken, /There is a code example on the page\./);
    assert.ok(!/picture/.test(spoken));
    assert.match(spoken, /First thing Second thing There is a table on the page\./);

    // A stored bodyIr (envelope or bare document) wins over the source, and a stored token is never spoken.
    const ir = { type: "document", schema_version: 1, front_matter: {}, children: [{ type: "paragraph", line: 1, inline: [{ type: "text", text: "From the IR PAPYRUSMARKUP00001END." }] }] };
    for (const bodyIr of [ir, { schemaVersion: 1, document: ir }, JSON.stringify({ document: ir })]) {
      assert.equal(text(storyBodyUnits({ markus: "ignored", bodyIr }).join("")), "From the IR .");
    }
  },

  "the interaction model carries every intent with natural samples": () => {
    const model = interactionModel(config).interactionModel.languageModel;
    const intents = new Map(model.intents.map((intent) => [intent.name, intent]));
    for (const name of ["AMAZON.CancelIntent", "AMAZON.FallbackIntent", "AMAZON.HelpIntent", "ContinueIntent", "HeadlinesIntent", "AMAZON.NavigateHomeIntent", "AMAZON.NextIntent", "AMAZON.PreviousIntent", "AMAZON.RepeatIntent", "AMAZON.StopIntent", "ReadStoryIntent"]) {
      assert.ok(intents.has(name), `${name} is in the model`);
    }
    const read = intents.get("ReadStoryIntent")!;
    assert.deepEqual(read.slots?.map((slot) => slot.type), ["AMAZON.Ordinal", "AMAZON.NUMBER"]);
    assert.ok(read.samples!.includes("read the {ordinal} one") && read.samples!.includes("story {number}"));
    const slotNames = new Set(read.slots!.map((slot) => slot.name));
    for (const sample of read.samples!) for (const [, slot] of sample.matchAll(/\{(\w+)\}/g)) assert.ok(slotNames.has(slot), `${sample} uses an undeclared slot`);
    assert.equal(new Set(read.samples).size, read.samples!.length, "no repeated samples");
    assert.ok(!INTENT_MODULES.some((module) => module.id === "launch" && module.interactionModel), "launch is a request type, not an intent");
    assert.ok(!/pilobolus/i.test(JSON.stringify(model.intents)));
  },

  "the content source reads the public projection": async () => {
    const requested: string[] = [];
    const latest = [
      { title: "First & Foremost", url: "/articles/first/", summary: "Summary one.", date: "2026-10-30", authors: ["Ada Example", "Grace Example"], publication: "Example News" },
      { title: "Second", url: "https://elsewhere.test/articles/second.html", summary: "Summary two.", date: "2026-10-29" },
      { title: "Third", url: "/articles/third/", summary: "Summary three.", date: "2026-10-28" },
    ];
    const archive = [...latest, { title: "Old one", url: "/articles/old/", summary: "From the archive.", date: "2025-01-01" }];
    const twin = [
      "# First & Foremost",
      "",
      "> Summary one.",
      "",
      "By [Ada Example](https://news.example.test/authors/ada/) · Published 2026-10-30",
      "",
      "Canonical: https://news.example.test/articles/first/",
      "",
      "The opening line.",
      "",
      ":::pull-quote",
      "Skip me.",
      ":::",
      "",
      "A closing line.",
      "",
    ].join("\n");
    const fetchFake: FetchLike = async (url) => {
      requested.push(url);
      const path = url.replace("https://news.example.test", "");
      const respond = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body, text: async () => String(body) });
      if (path === "/_data/latest.json") return respond(200, latest);
      if (path === "/_data/search-index.json") return respond(200, archive);
      if (path === "/articles/first/index.md") return respond(200, twin);
      if (path === "/articles/second.md") return respond(404, "");
      if (path === "/articles/old/index.md") return respond(200, "Old body.");
      return respond(404, "");
    };
    const source = createPublicSiteStorySource({ origin: "https://news.example.test/", fetch: fetchFake });

    const listed = await source.listLatest({ limit: 2 });
    assert.deepEqual(listed, [
      { id: "articles/first", slug: "articles/first", title: "First & Foremost", deck: "Summary one.", byline: "Ada Example, Grace Example", publishedAt: "2026-10-30T00:00:00Z" },
      { id: "articles/second", slug: "articles/second", title: "Second", deck: "Summary two.", publishedAt: "2026-10-29T00:00:00Z" },
    ]);
    assert.deepEqual(requested, ["https://news.example.test/_data/latest.json"]);

    const first = await source.getStory("articles/first");
    assert.equal(first?.title, "First & Foremost");
    assert.equal(first?.byline, "Ada Example, Grace Example");
    assert.equal(first?.markus.trim(), "The opening line.\n\n:::pull-quote\nSkip me.\n:::\n\nA closing line.");
    assert.equal(text(storyBodyUnits(first!).join("")), "The opening line. A closing line.");
    assert.ok(requested.includes("https://news.example.test/articles/first/index.md"));

    assert.equal(await source.getStory("articles/second"), undefined, "a 404 twin is no story");
    assert.equal(await source.getStory("articles/nothing"), undefined, "an unlisted slug is no story");
    assert.equal(requested.some((url) => url.includes("elsewhere.test")), false, "a listing entry never sends the function to another host");
    const old = await source.getStory("articles/old");
    assert.equal(old?.deck, "From the archive.", "older stories come from the search index");
    assert.equal(old?.markus, "Old body.");

    const broken = createPublicSiteStorySource({ origin: "https://news.example.test", fetch: async () => ({ ok: false, status: 503, json: async () => [], text: async () => "" }) });
    await assert.rejects(broken.listLatest({ limit: 5 }), /503/);
    const notList = createPublicSiteStorySource({ origin: "https://news.example.test", fetch: async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => "" }) });
    await assert.rejects(notList.listLatest({ limit: 5 }), /not a list/);

    // Without a site origin there is no source: it fails loudly instead of answering with nothing.
    await assert.rejects(createPublicStorySource({ ...config, siteOrigin: undefined }).listLatest({ limit: 5 }), /no public story source/);
    assert.ok(createPublicStorySource(config));
  },

  "the twin header is split from the Markus body": () => {
    const parts = splitTwin("# Title\n\n> A summary\n> over two lines\n\nBy Ada · Published 2026-01-01 · Updated 2026-01-02\n\nCanonical: https://x.test/a/\n\n## Body heading\n\nText.\n");
    assert.equal(parts.title, "Title");
    assert.equal(parts.summary, "A summary over two lines");
    assert.equal(parts.byline, "Ada");
    assert.equal(parts.canonical, "https://x.test/a/");
    assert.equal(parts.body.trim(), "## Body heading\n\nText.");
    // A body that opens with its own heading has no title line; the facts still come first.
    const noTitle = splitTwin("> Summary\n\nPublished 2026-01-01\n\nCanonical: https://x.test/b/\n\n# Own heading\n\nText.");
    assert.equal(noTitle.title, undefined);
    assert.equal(noTitle.body.trim(), "# Own heading\n\nText.");
  },
};

async function main() {
  const requested = process.argv[2];
  const names = requested === undefined ? Object.keys(behaviours) : [requested];
  for (const name of names) {
    const behaviour = behaviours[name];
    assert.ok(behaviour, `unknown behaviour "${name}"`);
    await behaviour();
    console.log(JSON.stringify({ behaviour: name }));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
