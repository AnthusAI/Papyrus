export type ArticleImageLayout = {
  minHeight: number;
  preferredHeight: number;
  maxHeight: number;
  aspectRatio: number;
  crop: "cover" | "contain";
  wrapsText: boolean;
  inlineFloat?: {
    minColumnCount?: number;
    columnSpan?: number;
    widthRatio?: number;
    narrowWidthRatio?: number;
    maxWidthRatio?: number;
    minWidth?: number;
  };
  focalPoint?: {
    x: number;
    y: number;
  };
};

export type ArticleImageThemeVariants = {
  dark?: {
    src: string;
  };
};

export type ArticleVideoThemeVariants = {
  light?: { src: string };
  dark?: { src: string };
};

export type ArticleImage = {
  src: string;
  alt: string;
  caption?: string;
  credit: string;
  layout?: ArticleImageLayout;
  themeVariants?: ArticleImageThemeVariants;
};

export type ArticleImageAsset = ArticleImage & {
  id: string;
  type: "image";
  roles?: Array<"lead" | "continuation" | "continuationInset" | "feature" | "thumbnail">;
};

export type ArticleVideoAsset = {
  id?: string;
  type: "video";
  src: string;
  posterSrc?: string;
  alt: string;
  caption?: string;
  credit: string;
  durationSeconds?: number;
  roles?: Array<"lead" | "feature" | "thumbnail">;
  themeVariants?: ArticleVideoThemeVariants;
};

export type ArticleAsset = ArticleImageAsset | ArticleVideoAsset;

export type Article = {
  slug: string;
  shortSlug?: string;
  section: string;
  headline: string;
  deck: string;
  excerpt?: string;
  byline: string;
  dateline: string;
  image?: ArticleImage;
  video?: ArticleVideoAsset;
  assets?: ArticleAsset[];
  pullQuotes?: string[];
  body: string[];
};

export const editionDate = "Wednesday, May 13, 2026";

export const articles: Article[] = [
  {
    slug: "agent-procedure-patterns",
    shortSlug: "AGENTS",
    section: "AI/ML",
    headline: "The Next Agent Breakthrough Is a Checklist",
    deck:
      "Developers are learning that reliable agents need less freedom, not more: state machines, scoped tools, policy gates, and step-by-step procedure.",
    byline: "Papyrus Staff",
    dateline: "NEWSROOM",
    image: {
      src: "/seed-art/workflow-lanes.png",
      alt: "An abstract workflow showing bounded editorial stages and handoffs",
      caption: "Bounded agents sit between rigid scripts and open-ended tool use.",
      credit: "Papyrus seed art",
      layout: {
        minHeight: 120,
        preferredHeight: 190,
        maxHeight: 360,
        aspectRatio: 1.5009,
        crop: "contain",
        wrapsText: true,
      },
    },
    pullQuotes: [
      "The practical breakthrough is not giving agents a bigger sandbox.",
      "A tiny tool-calling model can follow agent steps as long as the workflow is enforced outside the prompt.",
    ],
    body: [
      "Developers are learning that reliable agents need less freedom, not more: state machines, scoped tools, policy gates, and step-by-step procedure. The most interesting argument this week was not about a new frontier model. It was about how much freedom an AI agent should be allowed to have.",
      "Across demos, comments, and tool launches, builders kept circling the same answer: the practical breakthrough is not giving agents a bigger sandbox, but putting them inside a procedure. That marks a quiet reversal in the agent story. The first wave of agent demos sold autonomy: ask for an outcome and let the model decide what to do. The newer work is more cautious and more useful.",
      "It treats agency as a dial, not a switch. At one end are scripts, workflow engines, and RPA jobs: predictable, auditable, and brittle when reality changes. At the other end are open-ended agents that can plan, browse, call tools, edit files, and recover from surprises, but may also wander, repeat themselves, or take unsafe actions. The emerging middle ground is bounded agency.",
      "A model can improvise, but only inside states, allowed tools, review gates, and traceable transitions. The Statewright project drew attention because it says part of this out loud. Its author argues that agentic problem solving becomes more reliable when the problem is made smaller instead of the model larger.",
      "A planning state can get read-only tools. An implementation state can get edit tools. A testing state can get test commands. The model cannot skip the workflow because the workflow is enforced outside the prompt. That pattern is showing up elsewhere. A tiny tool-calling model can follow agent steps as long as the next action is constrained by a procedure.",
      "The lesson is not that agents are over. It is that they need architecture. The frontier is shifting from open-ended instruction following to systems that decide where the model is allowed to be creative and where the software should be boring. In practice, the checklist may be the most important agent interface.",
    ],
  },
  {
    slug: "schools-reading-lab",
    shortSlug: "READING",
    section: "Education",
    headline: "Reading Labs Replace Remediation With Daily Practice",
    deck:
      "Teachers are testing short, frequent literacy blocks that use live diagnostics without turning classrooms into test prep centers.",
    byline: "Jon Bell",
    dateline: "NORTHLINE",
    image: {
      src: "https://images.unsplash.com/photo-1509062522246-3755977927d7?auto=format&fit=crop&w=1000&q=80",
      alt: "Students working together at a classroom table",
      caption: "Students rotate through short reading-practice stations built around live diagnostics.",
      credit: "Classroom notebook",
      layout: {
        minHeight: 120,
        preferredHeight: 220,
        maxHeight: 420,
        aspectRatio: 4 / 3,
        crop: "cover",
        wrapsText: true,
      },
    },
    pullQuotes: [
      "The blocks last eighteen minutes. That is the point.",
      "The data is deliberately small: enough to choose tomorrow's grouping.",
    ],
    body: [
      "At 9:10 each morning, the fifth grade at Bellwether School breaks into a rhythm that looks more like music rehearsal than remediation. One group reads aloud with a teacher, one marks unfamiliar words in a science passage, one records a short explanation, and one works through a vocabulary ladder at the back table.",
      "The blocks last eighteen minutes. That is the point. Administrators wanted a model that could happen every day without swallowing social studies, art, or recess. The district's older intervention program pulled students from class twice a week and often arrived too late to change what happened in the next lesson.",
      "Now teachers receive a same-day view of fluency, comprehension, and vocabulary signals. The data is deliberately small: enough to choose tomorrow's grouping, not enough to rank children publicly. Teachers can override every recommendation, and many do.",
      "Early results are uneven but promising. Students who had stalled on multisyllabic decoding are moving fastest. English learners show gains when the passages connect to science and local history units. The hardest cases remain students who can decode accurately but lose the thread of an argument after the second paragraph.",
      "The district is watching teacher workload closely. A literacy coach visits each building twice a week, and the software vendor is barred from sending automated messages to families. Principals say the model will survive only if it feels like instruction rather than surveillance.",
    ],
  },
  {
    slug: "market-hall",
    shortSlug: "MARKET",
    section: "Business",
    headline: "Old Market Hall Finds a Second Life as a Food Factory",
    deck:
      "Small producers are sharing cold rooms, packaging lines, and a retail counter in a building once written off as obsolete.",
    byline: "Ilya Stone",
    dateline: "EASTBOROUGH",
    image: {
      src: "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=1000&q=80",
      alt: "A busy restaurant kitchen with stainless steel counters",
      caption: "The renovated market hall combines prep kitchens, storefront counters, and shared cold storage.",
      credit: "Kitchen file",
      layout: {
        minHeight: 110,
        preferredHeight: 210,
        maxHeight: 380,
        aspectRatio: 4 / 3,
        crop: "cover",
        wrapsText: false,
      },
    },
    pullQuotes: [
      "The economics depend on sharing.",
      "That counter has become its own kind of research lab.",
    ],
    body: [
      "The market hall's loading dock used to open twice a week. Now it opens before dawn. Bakers roll in racks of proofed dough, a salsa maker unloads crates of tomatillos, and a coffee roaster threads sacks of beans through a doorway that still bears the name of a grocer who closed in 1988.",
      "The renovation was less glamorous than the ribbon cutting suggested. Contractors replaced cracked drains, raised the electrical service, and carved one cavernous floor into a set of certified production rooms. The city provided low-interest financing because small food companies kept leaving town when they outgrew home kitchens but could not afford private facilities.",
      "The economics depend on sharing. Tenants reserve equipment by the hour and pay more for freezer space than for office space. A single compliance manager handles inspections, labeling questions, and recall drills. On Saturdays, a retail counter lets customers buy the products made during the week.",
      "That counter has become its own kind of research lab. Producers can test packaging, pricing, and flavors before committing to wholesale runs. The most popular item so far is a fermented pepper sauce that began as a farmers market experiment and now ships to three regional chains.",
      "Neighbors who feared another boutique food court have been cautiously won over by the number of industrial jobs. The hall employs dishwashers, packers, drivers, and maintenance workers, not only chefs with investors. The question is whether rents can stay low once the building becomes fashionable again.",
    ],
  },
  {
    slug: "river-court",
    section: "Civic Life",
    headline: "A Tiny Courtroom Tries to Keep Evictions From Becoming Homelessness",
    deck:
      "Mediators, rent ledgers, and emergency aid sit in the same hallway as judges in a new housing docket.",
    byline: "Anika Rao",
    dateline: "MILL COUNTY",
    image: {
      src: "https://images.unsplash.com/photo-1589578527966-fdac0f44566c?auto=format&fit=crop&w=1000&q=80",
      alt: "Sunlight through the columns of a courthouse",
      caption: "Court administrators are balancing public-record access with case-management automation.",
      credit: "Courthouse file",
      layout: {
        minHeight: 120,
        preferredHeight: 230,
        maxHeight: 420,
        aspectRatio: 1.5,
        crop: "cover",
        wrapsText: true,
      },
    },
    pullQuotes: [
      "The first question has changed from who is at fault to whether the tenancy can be stabilized.",
      "The shelter system has not opened an overflow wing this spring.",
    ],
    body: [
      "The housing docket meets in Courtroom 2B, a narrow room with a flickering clock and a stack of folding chairs outside the door. By 8:30, landlords, tenants, lawyers, and caseworkers have filled the hallway. Some hold lease packets. Some hold money orders. Almost everyone is checking a phone.",
      "The premise is simple: most eviction cases turn on missed payments that are smaller than the public cost of sheltering a displaced family. The county now places rental assistance screeners, legal aid lawyers, and mediators next to the courtroom so agreements can be reached before a writ is issued.",
      "Judges still hear contested cases, and landlords can still recover possession. But the first question has changed from who is at fault to whether the tenancy can be stabilized. A tenant with a new job may need a payment plan. A landlord with a small mortgage may need partial payment within days. A caseworker may be able to close the gap with emergency funds.",
      "The docket has reduced default judgments because tenants are more likely to appear when help is available on site. It has also exposed how thin the safety net remains. Assistance funds run out before the month does, and many renters arrive only after fees have doubled the original balance.",
      "County leaders are debating whether to make the docket permanent. The strongest argument may be the quietest one: the shelter system has not opened an overflow wing this spring.",
    ],
  },
  {
    slug: "night-trains",
    section: "Travel",
    headline: "Night Trains Return With Sleeper Cars and Skeptics",
    deck:
      "A revived overnight route promises downtown-to-downtown travel, but reliability will decide whether curiosity becomes habit.",
    byline: "Theo Mercer",
    dateline: "CENTRAL STATION",
    image: {
      src: "https://images.unsplash.com/photo-1474487548417-781cb71495f3?auto=format&fit=crop&w=1000&q=80",
      alt: "A passenger train waiting at a platform",
      caption: "Regional rail planners are testing later departures before committing to permanent schedules.",
      credit: "Rail archive",
      layout: {
        minHeight: 110,
        preferredHeight: 210,
        maxHeight: 360,
        aspectRatio: 1.5,
        crop: "cover",
        wrapsText: false,
      },
    },
    pullQuotes: [
      "The real test comes in winter, when novelty fades.",
      "A moving bedroom must be dependable enough for business and family visits.",
    ],
    body: [
      "The new sleeper train leaves at 10:42 p.m., late enough for dinner and early enough for a child to fall asleep before the suburbs thin out. By morning it reaches the capital, sliding under the old glass roof while commuters are still buying coffee.",
      "Rail officials have tried this before. Overnight service faded as cheap flights multiplied, maintenance windows shrank, and older cars became expensive to keep in service. This revival is different in two ways: the route uses refurbished cars with private rooms, and the schedule is aimed at travelers who would otherwise lose a day to airports.",
      "The train's supporters talk about carbon, comfort, and city-center convenience. Its critics talk about freight congestion, missed connections, and the long memory of routes that launched with enthusiasm and died quietly two timetables later.",
      "The first month is nearly sold out, helped by nostalgia and a marketing campaign heavy on brass lamps and linen sheets. The real test comes in winter, when novelty fades and travelers decide whether a moving bedroom is dependable enough for business, family visits, and holidays.",
    ],
  },
  {
    slug: "climate-ledger",
    section: "Science",
    headline: "Researchers Build a Climate Ledger for City Blocks",
    deck:
      "A block-by-block model gives planners a sharper picture of heat, shade, runoff, and retrofit payoffs.",
    byline: "Celeste Ng",
    dateline: "WEST QUAY",
    image: {
      src: "https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?auto=format&fit=crop&w=1000&q=80",
      alt: "A satellite view of Earth and weather systems",
      caption: "Small climate ledgers increasingly rely on satellite checks instead of annual surveys.",
      credit: "Remote sensing",
      layout: {
        minHeight: 120,
        preferredHeight: 240,
        maxHeight: 440,
        aspectRatio: 1.5,
        crop: "cover",
        wrapsText: true,
      },
    },
    pullQuotes: [
      "The output is not a single score but a set of tradeoffs.",
      "A block can now be flagged as data-poor rather than quietly misclassified.",
    ],
    body: [
      "City climate maps have usually been blunt instruments. They show neighborhoods that are hotter, wetter, or more vulnerable than others, but they rarely tell a planner which block should get trees before pavement, which roof should get reflective coating, or which alley can absorb stormwater before it reaches a basement.",
      "A research team at West Quay University is trying to narrow the unit of action. Their model combines tree canopy, roof material, surface temperature, drainage complaints, utility burden, and building age into a ledger for each block. The output is not a single score but a set of tradeoffs.",
      "On one block, shade trees may reduce afternoon heat but interfere with buried utilities. On another, a cool-roof program may help renters only if paired with rules that prevent landlords from passing the cost through immediately. A third block may need porous pavement more than shade because runoff is the dominant risk.",
      "The team built the tool with public data where possible and marked uncertain estimates in plain language. Community groups pushed for that feature after seeing earlier maps turn shaky data into confident colors. A block can now be flagged as data-poor rather than quietly misclassified.",
      "The city plans to use the ledger in next year's capital budget. Researchers warn that the model should guide site visits, not replace them. A spreadsheet can see heat islands. It cannot see a grandmother who sits on the same stoop every afternoon because it is the only shaded place on the block.",
    ],
  },
];

export function getArticle(slug: string): Article | undefined {
  return articles.find((article) => article.slug === slug);
}

export function getArticleText(article: Article): string {
  return article.body.join("\n\n");
}

export function getArticleImageAssets(article: Article): ArticleImageAsset[] {
  const imageAssets = article.assets?.filter((asset): asset is ArticleImageAsset => asset.type === "image") ?? [];
  if (imageAssets.length > 0) return imageAssets;
  if (!article.image) return [];

  return [
    {
      ...article.image,
      id: `${article.slug}-primary-image`,
      type: "image",
      roles: ["lead", "continuation", "continuationInset"],
    },
  ];
}

export function getArticleVideoAsset(article: Article): ArticleVideoAsset | undefined {
  const videoAssets = article.assets?.filter((asset): asset is ArticleVideoAsset => asset.type === "video") ?? [];
  if (videoAssets.length > 0) {
    return videoAssets.find((asset) => asset.roles?.includes("lead")) ?? videoAssets[0];
  }
  return article.video;
}
