/*
 * Reader islands for a static Papyrus site (the reader-steering plugin, contract 1).
 *
 * Framework-free and dependency-free. Load it once, beside the islands runtime:
 *   <script src="/_plugins/papyrus-reader@1.js" defer></script>
 *   <link rel="stylesheet" href="/_plugins/papyrus-reader@1.css">
 * and place mount points where the site owns the HTML (an article template, the header):
 *   <div data-island="ReaderSignIn"></div>
 *   <div data-island="Vote" data-props='{"subject":"<item key>","up":3}'></div>
 *   <div data-island="Vote" data-props='{"type":"proposal","id":"<proposal id>","up":2,"down":1}'></div>   (any subject type: up and down)
 *   <div data-island="Flag" data-props='{"type":"proposal","id":"<proposal id>"}'></div>   (wrong, belongs under, better name; each with a reason)
 *   <div data-island="UsedIt" data-props='{"subject":"<item key>","usedIt":1}'></div>
 *   <div data-island="Rating" data-props='{"subject":"<item key>","dimensions":["real","useful"]}'></div>
 *   <div data-island="Freshness" data-props='{"generatedAt":"2026-10-21T10:00:00Z"}'></div>
 *   <div data-island="Submit" data-props='{"kinds":["article","tool"]}'></div>   (the /submit/ page)
 *   <div data-island="Comments" data-props='{"subject":"<item key>"}'></div>   (an item page; optional "editMinutes", "maximumLength")
 *   <div data-island="RankedList" data-props='{"list":"rising","limit":10,"section":"tools","empty":"Nothing is rising yet."}'></div>   (list: front, rising or new; from board.json and subjects.json)
 *   <div data-island="Report" data-props='{"target":"<submission id or comment id>"}'></div>   (next to a listed submission)
 *
 * The script registers its islands in window.papyrusIslands and also mounts any [data-island] of its own names, once, so
 * it works with or without the core islands runtime. Props prerender the last snapshot values; the page then fetches
 * <base>_data/reader/items.json, refetches it every 60 seconds while the tab is visible, and asks /api/reader/me
 * for the reader's own votes. Site settings: window.papyrusReader = { base: "/", api: "/api/reader", signIn: "...", signOut: "...",
 * voteSubjects: ["item", "proposal"] }. voteSubjects lists the enabled vote subject types (the backend's subjects.types; default
 * item and submission); the script also sets window.papyrusReader.proposalVoting = voteSubjects.includes("proposal").
 *
 * Every state is words as well as styling, buttons carry aria-pressed, and while the API answers 503
 * reader_identity_unavailable every control is disabled and says "Reader sign-in is not open yet".
 */
(function () {
  "use strict";

  var settings = Object.assign(
    { base: "/", api: "/api/reader", signIn: "/api/auth/prospectus/sign-in", signOut: "/api/auth/prospectus/sign-out", pollSeconds: 60 },
    window.papyrusReader || {}
  );
  // The subject types the publication lets readers vote on (custom.papyrusPlugins["reader-steering"].subjects.types in
  // amplify_outputs.json; the site copies it into window.papyrusReader.voteSubjects). Without it: items and submissions.
  var voteSubjects = Array.isArray(settings.voteSubjects) ? settings.voteSubjects.filter(function (type) { return typeof type === "string"; }) : ["item", "submission"];
  settings.voteSubjects = voteSubjects;
  settings.proposalVoting = voteSubjects.indexOf("proposal") !== -1;
  window.papyrusReader = Object.assign(window.papyrusReader || {}, { voteSubjects: voteSubjects, proposalVoting: settings.proposalVoting });
  var SUBJECTS_PER_REQUEST = 50;
  var TEXT = {
    loading: "Checking sign-in",
    unavailable: "Reader sign-in is not open yet",
    signedOut: "Sign in to vote and rate",
    failed: "Something went wrong. Try again later.",
    notRated: "Not rated",
    signInDeclined: "Sign-in was cancelled.",
    signInFailed: "Sign-in did not complete. Try again.",
    typeOff: "Voting on this is not open yet"
  };

  /* A failed sign-in comes back to the page it started from with ?sign_in_error=<code> (never an /api page): say so once, then tidy the address. */
  var signInProblem = "";
  var signInProblemCode = "";
  try {
    var problems = new URLSearchParams(location.search);
    if (problems.has("sign_in_error")) {
      var signInCode = problems.get("sign_in_error");
      signInProblem = signInCode === "sign_in_declined" ? TEXT.signInDeclined : TEXT.signInFailed;
      /* The code is shown in small print so a reader can report it; only a plain lower-case code is ever shown. */
      if (signInCode !== "sign_in_declined" && /^[a-z0-9_]{1,60}$/.test(signInCode)) signInProblemCode = signInCode;
      problems.delete("sign_in_error");
      history.replaceState(null, "", location.pathname + (problems.toString() ? "?" + problems.toString() : "") + location.hash);
    }
  } catch (error) { signInProblem = ""; signInProblemCode = ""; }

  var DEFAULT_DISPLAY_MINIMUM = 5;
  var state = { identity: "loading", me: null, snapshot: null, parameters: null, adjustments: {}, handleMessage: "" };
  var subjects = {};
  var subscribers = [];
  var loadingMe = null;

  function subscribe(render) {
    subscribers.push(render);
    render();
  }

  function notify() {
    subscribers.forEach(function (render) { render(); });
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function plural(count, one, many) {
    return count + " " + (count === 1 ? one : many);
  }

  function parseProps(host) {
    try { return JSON.parse(host.getAttribute("data-props") || "{}"); } catch (error) { return {}; }
  }

  function retryText(seconds) {
    var minutes = Math.max(1, Math.ceil((Number(seconds) || 60) / 60));
    return "Too many actions. Try again in about " + plural(minutes, "minute", "minutes") + ".";
  }

  function readJson(response) {
    return response.json().catch(function () { return {}; });
  }

  function requestMe(subject) {
    if (subject) subjects[subject] = true;
    clearTimeout(loadingMe);
    loadingMe = setTimeout(loadMe, 0);
  }

  function loadMe() {
    var keys = Object.keys(subjects);
    var chunks = [];
    for (var start = 0; start < Math.max(keys.length, 1); start += SUBJECTS_PER_REQUEST) chunks.push(keys.slice(start, start + SUBJECTS_PER_REQUEST));
    return Promise.all(chunks.map(function (chunk) {
      var query = chunk.length ? "?subjects=" + chunk.map(encodeURIComponent).join(",") : "";
      return fetch(settings.api + "/me" + query, { credentials: "same-origin", headers: { accept: "application/json" } })
        .then(function (response) { return readJson(response).then(function (body) { return { status: response.status, body: body }; }); });
    })).then(function (answers) {
      var failed = answers.filter(function (answer) { return answer.status !== 200; })[0];
      if (failed) {
        state.identity = failed.status === 401 ? "signed-out" : failed.status === 503 && failed.body.error === "reader_identity_unavailable" ? "unavailable" : "error";
        state.me = null;
      } else {
        state.identity = "signed-in";
        state.me = Object.assign({}, answers[0].body, { votes: {} });
        answers.forEach(function (answer) { Object.assign(state.me.votes, answer.body.votes || {}); });
      }
      notify();
    }).catch(function () {
      state.identity = "error";
      notify();
    });
  }

  // The reader-count floor for showing a mean: board.json parameters (displayMinimum, else hypeMinimum, else readerMinimum), else 5.
  function displayMinimum() {
    var parameters = state.parameters || {};
    var names = ["displayMinimum", "hypeMinimum", "readerMinimum"];
    for (var index = 0; index < names.length; index += 1) {
      var value = Number(parameters[names[index]]);
      if (parameters[names[index]] != null && isFinite(value) && value >= 1) return value;
    }
    return DEFAULT_DISPLAY_MINIMUM;
  }

  function loadParameters() {
    return fetch(settings.base + "_data/reader/board.json", { credentials: "omit", cache: "no-cache" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (board) {
        if (board && board.parameters && typeof board.parameters === "object") { state.parameters = board.parameters; notify(); }
      })
      .catch(function () {});
  }

  function loadSnapshot() {
    loadParameters();
    return fetch(settings.base + "_data/reader/items.json", { credentials: "omit", cache: "no-cache" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (snapshot) {
        if (!snapshot || !snapshot.items) return;
        state.snapshot = snapshot;
        var generated = Date.parse(snapshot.generatedAt);
        Object.keys(state.adjustments).forEach(function (key) {
          if (generated >= state.adjustments[key].at) delete state.adjustments[key];
        });
        notify();
      })
      .catch(function () {});
  }

  function poll() {
    if (document.visibilityState === "visible") loadSnapshot();
  }

  function startPolling() {
    setInterval(poll, settings.pollSeconds * 1000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") { loadSnapshot(); notify(); }
    });
    loadSnapshot();
  }

  function snapshotItem(subject) {
    return (state.snapshot && state.snapshot.items && state.snapshot.items[subject]) || null;
  }

  function mine(subject, dimension) {
    var votes = state.me && state.me.votes && state.me.votes[subject];
    return votes && votes[dimension] ? votes[dimension] : 0;
  }

  function adjusted(subject, dimension, base) {
    var adjustment = state.adjustments[subject + "#" + dimension];
    return Math.max(0, base + (adjustment ? adjustment.delta : 0));
  }

  function typeEnabled(type) {
    return voteSubjects.indexOf(type) !== -1;
  }

  function controlStatus() {
    if (state.identity === "loading") return TEXT.loading;
    if (state.identity === "unavailable") return TEXT.unavailable;
    if (state.identity === "signed-out") return TEXT.signedOut;
    if (state.identity === "error") return TEXT.failed;
    return "";
  }

  function post(path, body) {
    return fetch(settings.api + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(body)
    }).then(function (response) {
      return readJson(response).then(function (payload) {
        if (response.status === 401) { state.identity = "signed-out"; state.me = null; notify(); }
        if (response.status === 503 && payload.error === "reader_identity_unavailable") { state.identity = "unavailable"; state.me = null; notify(); }
        return { ok: response.ok, status: response.status, body: payload };
      });
    });
  }

  function failureText(result) {
    if (result.status === 429) return retryText(result.body.retryAfter);
    if (result.status === 401) return TEXT.signedOut;
    if (result.status === 503) return TEXT.unavailable;
    return (result.body && result.body.message) || TEXT.failed;
  }

  function writeVote(subject, dimension, value, previous) {
    var path = dimension === "up" || dimension === "used-it" ? "/vote" : "/rating";
    var body = path === "/vote" ? { subject: subject, dimension: dimension, on: value !== null } : { subject: subject, dimension: dimension, value: value };
    var votes = (state.me.votes[subject] = state.me.votes[subject] || {});
    var key = subject + "#" + dimension;
    var before = state.adjustments[key];
    if (value === null) delete votes[dimension]; else votes[dimension] = value;
    if (path === "/vote") state.adjustments[key] = { delta: (before ? before.delta : 0) + (value !== null ? 1 : 0) - (previous ? 1 : 0), at: Date.now() };
    notify();
    return post(path, body).then(function (result) {
      if (result.ok) return "";
      if (previous) votes[dimension] = previous; else delete votes[dimension];
      if (before) state.adjustments[key] = before; else delete state.adjustments[key];
      notify();
      return failureText(result);
    }).catch(function () {
      if (previous) votes[dimension] = previous; else delete votes[dimension];
      if (before) state.adjustments[key] = before; else delete state.adjustments[key];
      notify();
      return TEXT.failed;
    });
  }

  function enabled() {
    return state.identity === "signed-in";
  }

  function toggleIsland(host, props, options) {
    var subject = props.subject;
    requestMe(subject);
    var button = element("button", "papyrus-reader-button");
    button.type = "button";
    var count = element("span", "papyrus-reader-count");
    var status = element("span", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    host.classList.add("papyrus-reader-control");
    host.appendChild(button);
    host.appendChild(count);
    host.appendChild(status);
    var message = "";
    var busy = false;
    subscribe(function () {
      var item = snapshotItem(subject);
      var base = state.snapshot ? (item ? item[options.field] : 0) : Number(props[options.field] || 0);
      var pressed = mine(subject, options.dimension) > 0;
      button.setAttribute("aria-pressed", pressed ? "true" : "false");
      button.textContent = pressed ? options.onLabel : options.offLabel;
      button.disabled = !enabled();
      button.setAttribute("aria-busy", busy ? "true" : "false");
      count.textContent = options.countText(adjusted(subject, options.dimension, base));
      status.textContent = message || controlStatus();
    });
    button.addEventListener("click", function () {
      if (!enabled() || busy) return;
      busy = true;
      message = "";
      var previous = mine(subject, options.dimension);
      writeVote(subject, options.dimension, previous ? null : 1, previous).then(function (failure) {
        busy = false;
        message = failure;
        notify();
      });
    });
  }

  // The subject key votes are stored and listed under: the bare id for items and submissions, "type:id" for the other types.
  function subjectKeyOf(type, id) {
    return type === "item" || type === "submission" ? id : type + ":" + id;
  }

  function snapshotCounts(key, props) {
    var item = snapshotItem(key);
    var from = state.snapshot ? item || {} : props;
    var adjustment = state.adjustments[key + "#vote"] || { up: 0, down: 0 };
    return { up: Math.max(0, Number(from.up || 0) + adjustment.up), down: Math.max(0, Number(from.down || 0) + adjustment.down) };
  }

  // Up and down on any subject type. Words and shapes carry the state (a triangle and "Voted up"), never colour alone.
  function mountTypedVote(host, props) {
    var type = props.type, id = props.id, key = subjectKeyOf(type, id);
    requestMe(key);
    host.classList.add("papyrus-reader-control");
    var up = element("button", "papyrus-reader-button");
    var down = element("button", "papyrus-reader-button");
    up.type = down.type = "button";
    var count = element("span", "papyrus-reader-count");
    var status = element("span", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    [up, down, count, status].forEach(function (node) { host.appendChild(node); });
    var message = "";
    var busy = false;
    subscribe(function () {
      var mineNow = mine(key, "up");
      var counts = snapshotCounts(key, props);
      up.setAttribute("aria-pressed", mineNow === 1 ? "true" : "false");
      down.setAttribute("aria-pressed", mineNow === -1 ? "true" : "false");
      up.textContent = mineNow === 1 ? "\u25B2 Voted up" : "\u25B3 Vote up";
      down.textContent = mineNow === -1 ? "\u25BC Voted down" : "\u25BD Vote down";
      up.disabled = down.disabled = !enabled() || !typeEnabled(type);
      up.setAttribute("aria-busy", busy ? "true" : "false");
      down.setAttribute("aria-busy", busy ? "true" : "false");
      count.textContent = plural(counts.up, "vote up", "votes up") + ", " + plural(counts.down, "vote down", "votes down");
      status.textContent = message || controlStatus() || (typeEnabled(type) ? "" : TEXT.typeOff);
    });
    function cast(clicked) {
      if (!enabled() || !typeEnabled(type) || busy) return;
      busy = true;
      message = "";
      var previous = mine(key, "up");
      var next = previous === clicked ? null : clicked;
      var votes = (state.me.votes[key] = state.me.votes[key] || {});
      var before = state.adjustments[key + "#vote"] || { up: 0, down: 0 };
      function apply(from, to) {
        if (to === null) delete votes.up; else votes.up = to;
        state.adjustments[key + "#vote"] = {
          up: before.up + (to === 1 ? 1 : 0) - (from === 1 ? 1 : 0),
          down: before.down + (to === -1 ? 1 : 0) - (from === -1 ? 1 : 0),
          delta: 0,
          at: Date.now()
        };
      }
      function undo() {
        if (previous) votes.up = previous; else delete votes.up;
        state.adjustments[key + "#vote"] = before;
      }
      apply(previous, next);
      notify();
      post("/vote", { subject: { type: type, id: id }, value: next }).then(function (result) {
        if (!result.ok) { undo(); message = failureText(result); }
      }).catch(function () { undo(); message = TEXT.failed; }).then(function () {
        busy = false;
        notify();
      });
    }
    up.addEventListener("click", function () { cast(1); });
    down.addEventListener("click", function () { cast(-1); });
  }

  var FLAG_KINDS = [
    { value: "wrong", label: "This is wrong" },
    { value: "belongs_under", label: "This belongs under\u2026" },
    { value: "better_name", label: "Suggest a better name" }
  ];

  function field(form, labelText, control) {
    var id = "papyrus-reader-flag-" + Math.random().toString(36).slice(2);
    var label = element("label", "papyrus-reader-field-label", labelText);
    control.id = id;
    label.setAttribute("for", id);
    var wrapper = element("div", "papyrus-reader-field");
    wrapper.appendChild(label);
    wrapper.appendChild(control);
    form.appendChild(wrapper);
    return wrapper;
  }

  // Flag a subject of any type as wrong, as belonging under another subject, or as needing a better name, always with a reason.
  function mountFlag(host, props) {
    var type = props.type, id = props.id;
    requestMe();
    host.classList.add("papyrus-reader-control", "papyrus-reader-flag");
    var open = element("button", "papyrus-reader-button", "\u2691 Flag");
    open.type = "button";
    open.setAttribute("aria-expanded", "false");
    var form = element("form", "papyrus-reader-flag-form");
    form.hidden = true;
    var kind = element("select", "papyrus-reader-input");
    kind.name = "kind";
    FLAG_KINDS.forEach(function (entry) { var option = element("option", "", entry.label); option.value = entry.value; kind.appendChild(option); });
    field(form, "What is the problem?", kind);
    var targetTypes = props.targetTypes || ["concept", "story", "proposal", "item"];
    var targetType = element("select", "papyrus-reader-input");
    targetType.name = "targetType";
    targetTypes.forEach(function (name) { var option = element("option", "", name); option.value = name; targetType.appendChild(option); });
    var targetId = element("input", "papyrus-reader-input");
    targetId.type = "text"; targetId.name = "targetId"; targetId.maxLength = 190; targetId.autocomplete = "off";
    var targetRow = element("div", "papyrus-reader-field");
    field(targetRow, "Type of the subject it belongs under", targetType);
    field(targetRow, "Id of the subject it belongs under", targetId);
    targetRow.hidden = true;
    form.appendChild(targetRow);
    var name = element("input", "papyrus-reader-input");
    name.type = "text"; name.name = "name"; name.maxLength = 120; name.autocomplete = "off";
    var nameRow = field(form, "Your suggested name", name);
    nameRow.hidden = true;
    var reason = element("textarea", "papyrus-reader-input");
    reason.name = "reason"; reason.maxLength = 500; reason.required = true; reason.rows = 3;
    field(form, "Why? (required, at most 500 characters)", reason);
    var send = element("button", "papyrus-reader-button", "Send flag");
    send.type = "submit";
    form.appendChild(send);
    var status = element("span", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    [open, form, status].forEach(function (node) { host.appendChild(node); });
    var message = "";
    subscribe(function () {
      open.disabled = !enabled() || !typeEnabled(type);
      send.disabled = open.disabled;
      status.textContent = message || controlStatus() || (typeEnabled(type) ? "" : TEXT.typeOff);
    });
    function showKind() {
      targetRow.hidden = kind.value !== "belongs_under";
      nameRow.hidden = kind.value !== "better_name";
      targetId.required = kind.value === "belongs_under";
      name.required = kind.value === "better_name";
    }
    kind.addEventListener("change", showKind);
    showKind();
    open.addEventListener("click", function () {
      form.hidden = !form.hidden;
      open.setAttribute("aria-expanded", form.hidden ? "false" : "true");
      if (!form.hidden) kind.focus();
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!enabled() || send.getAttribute("aria-busy") === "true" || !reason.value.trim()) return;
      var body = { subject: { type: type, id: id }, kind: kind.value, reason: reason.value };
      if (kind.value === "belongs_under") body.target = { type: targetType.value, id: targetId.value.trim() };
      if (kind.value === "better_name") body.name = name.value;
      send.setAttribute("aria-busy", "true");
      message = "";
      post("/flag", body).then(function (result) {
        send.setAttribute("aria-busy", "false");
        if (result.ok) {
          form.hidden = true;
          open.setAttribute("aria-expanded", "false");
          reason.value = ""; name.value = ""; targetId.value = "";
          message = "Flag sent. Thank you.";
        } else {
          message = failureText(result);
        }
        notify();
      }).catch(function () { send.setAttribute("aria-busy", "false"); message = TEXT.failed; notify(); });
    });
  }

  function mountVote(host, props) {
    if (props.type && props.id) return mountTypedVote(host, props);
    toggleIsland(host, props, {
      dimension: "up", field: "up", offLabel: "Upvote", onLabel: "Upvoted",
      countText: function (count) { return plural(count, "upvote", "upvotes"); }
    });
  }

  function mountUsedIt(host, props) {
    toggleIsland(host, props, {
      dimension: "used-it", field: "usedIt", offLabel: "I used it", onLabel: "You used it",
      countText: function (count) { return plural(count, "reader used it", "readers used it"); }
    });
  }

  function statsText(stats) {
    return stats && stats.n ? Number(stats.mean).toFixed(1) + " from " + plural(stats.n, "rating", "ratings") : "no ratings yet";
  }

  // Reader stats: below the floor the mean is withheld ("n=3, too few"), never shown with a count that small.
  function readerTooFew(stats) {
    return !!(stats && stats.n && stats.n < displayMinimum());
  }

  function readerText(stats) {
    return readerTooFew(stats) ? "n=" + stats.n + ", too few" : statsText(stats);
  }

  // Five segments: filled ones are solid, empty ones outlined; withheld (too few) is all empty and dimmed.
  function meter() {
    var node = element("span", "papyrus-reader-meter");
    node.setAttribute("aria-hidden", "true");
    for (var index = 0; index < 5; index += 1) node.appendChild(element("span", "papyrus-reader-meter-segment"));
    return node;
  }

  function fillMeter(node, stats) {
    var filled = stats && stats.n && !readerTooFew(stats) ? Math.round(Number(stats.mean)) : 0;
    node.classList.toggle("papyrus-reader-meter-withheld", readerTooFew(stats));
    Array.prototype.forEach.call(node.children, function (segment, index) {
      segment.classList.toggle("papyrus-reader-meter-filled", index < filled);
    });
  }

  function whyForm(subject, dimension) {
    var form = element("form", "papyrus-reader-why");
    form.hidden = true;
    var input = element("input", "papyrus-reader-input");
    input.type = "text"; input.name = "why"; input.maxLength = 500; input.autocomplete = "off";
    input.id = "papyrus-reader-why-" + dimension + "-" + Math.random().toString(36).slice(2);
    var label = element("label", "papyrus-reader-field-label", "Why? (optional, public)");
    label.setAttribute("for", input.id);
    var send = element("button", "papyrus-reader-button", "Post reason");
    send.type = "submit";
    var status = element("span", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    [label, input, send, status].forEach(function (node) { form.appendChild(node); });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var value = mine(subject, dimension);
      if (!input.value.trim() || !value || send.getAttribute("aria-busy") === "true") return;
      send.setAttribute("aria-busy", "true");
      status.textContent = "";
      post("/comment", { subject: subject, body: input.value, ratingContext: { dimension: dimension, value: value } }).then(function (result) {
        send.setAttribute("aria-busy", "false");
        if (result.ok) {
          rememberComment(subject, result.body);
          input.value = "";
          status.textContent = "Posted. It shows in the comments with the next update.";
        } else {
          status.textContent = failureText(result);
        }
      }).catch(function () { send.setAttribute("aria-busy", "false"); status.textContent = TEXT.failed; });
    });
    return {
      form: form,
      reset: function () { input.value = ""; status.textContent = ""; },
      refresh: function () { input.disabled = !enabled(); send.disabled = !enabled(); }
    };
  }

  function mountRating(host, props) {
    var subject = props.subject;
    var dimensions = Array.isArray(props.dimensions) ? props.dimensions : [];
    requestMe(subject);
    host.classList.add("papyrus-reader-control", "papyrus-reader-rating");
    var rows = dimensions.map(function (dimension) {
      var group = element("div", "papyrus-reader-rating-row");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", dimension);
      var label = element("span", "papyrus-reader-rating-label", dimension);
      var buttons = [1, 2, 3, 4, 5].map(function (value) {
        var button = element("button", "papyrus-reader-button papyrus-reader-star", String(value));
        button.type = "button";
        button.setAttribute("aria-label", "Rate " + dimension + " " + value + " of 5");
        group.appendChild(button);
        return button;
      });
      var own = element("span", "papyrus-reader-own");
      var readers = element("span", "papyrus-reader-stats");
      var readerMeter = meter();
      var editor = element("span", "papyrus-reader-stats");
      group.insertBefore(label, group.firstChild);
      group.appendChild(own);
      group.appendChild(readerMeter);
      group.appendChild(readers);
      group.appendChild(editor);
      host.appendChild(group);
      var why = whyForm(subject, dimension);
      host.appendChild(why.form);
      return { dimension: dimension, buttons: buttons, own: own, readers: readers, meter: readerMeter, editor: editor, busy: false, why: why, askWhy: false };
    });
    var raters = element("p", "papyrus-reader-raters");
    host.appendChild(raters);
    var status = element("p", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    host.appendChild(status);
    var message = "";
    subscribe(function () {
      var item = snapshotItem(subject);
      var prerendered = props.ratings || {};
      var ratersCount = state.snapshot ? (item && item.raters) : props.raters;
      raters.textContent = typeof ratersCount === "number" ? ratersCount + " rated it" : "";
      rows.forEach(function (row) {
        var published = state.snapshot ? item && item.ratings && item.ratings[row.dimension] : prerendered[row.dimension];
        var value = mine(subject, row.dimension);
        row.buttons.forEach(function (button, index) {
          button.setAttribute("aria-pressed", value === index + 1 ? "true" : "false");
          button.disabled = !enabled();
          button.setAttribute("aria-busy", row.busy ? "true" : "false");
        });
        row.own.textContent = value ? "Your rating: " + value + " of 5" : TEXT.notRated;
        if (!value) row.askWhy = false;
        row.why.form.hidden = !(row.askWhy && value && enabled());
        row.why.refresh();
        row.readers.textContent = "Readers: " + readerText(published && published.reader);
        fillMeter(row.meter, published && published.reader);
        row.editor.textContent = published && published.editor && published.editor.n ? "Editor: " + statsText(published.editor) : "";
      });
      status.textContent = message || controlStatus();
    });
    rows.forEach(function (row) {
      row.buttons.forEach(function (button, index) {
        button.addEventListener("click", function () {
          if (!enabled() || row.busy) return;
          row.busy = true;
          message = "";
          var previous = mine(subject, row.dimension);
          var next = previous === index + 1 ? null : index + 1;
          writeVote(subject, row.dimension, next, previous).then(function (failure) {
            row.busy = false;
            message = failure;
            row.askWhy = !failure && next !== null;
            if (row.askWhy) row.why.reset();
            notify();
          });
        });
      });
    });
  }

  function ago(generatedAt) {
    var seconds = Math.max(0, (Date.now() - Date.parse(generatedAt)) / 1000);
    if (isNaN(seconds)) return "";
    if (seconds < 60) return "Updated just now";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return "Updated " + minutes + " min ago";
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return "Updated " + plural(hours, "hour", "hours") + " ago";
    return "Updated " + plural(Math.floor(hours / 24), "day", "days") + " ago";
  }

  function mountFreshness(host, props) {
    var time = element("time", "papyrus-reader-freshness");
    host.appendChild(time);
    subscribe(function () {
      var generatedAt = (state.snapshot && state.snapshot.generatedAt) || props.generatedAt;
      time.textContent = generatedAt ? ago(generatedAt) : "Live numbers have not loaded yet";
      if (generatedAt) time.setAttribute("datetime", generatedAt);
    });
    setInterval(function () { if (document.visibilityState === "visible") notify(); }, 30000);
  }

  function handleForm(host) {
    var form = element("form", "papyrus-reader-handle-form");
    var label = element("label", "papyrus-reader-handle-label", "Choose a handle");
    var input = element("input", "papyrus-reader-handle-input");
    input.type = "text";
    input.name = "handle";
    input.required = true;
    input.minLength = 3;
    input.maxLength = 24;
    input.pattern = "[A-Za-z0-9_\\-]{3,24}";
    input.autocomplete = "off";
    input.id = "papyrus-reader-handle-" + Math.random().toString(36).slice(2);
    label.setAttribute("for", input.id);
    var hint = element("span", "papyrus-reader-hint", "3 to 24 letters, digits, hyphens or underscores. You can set it once.");
    var save = element("button", "papyrus-reader-button", "Save handle");
    save.type = "submit";
    var message = element("span", "papyrus-reader-status");
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    [label, input, hint, save, message].forEach(function (node) { form.appendChild(node); });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (save.getAttribute("aria-busy") === "true") return;
      save.setAttribute("aria-busy", "true");
      message.textContent = "";
      post("/handle", { handle: input.value }).then(function (result) {
        save.setAttribute("aria-busy", "false");
        if (result.ok) {
          state.me.handle = result.body.handle;
          notify();
        } else if (result.status === 409 && result.body.error === "handle_taken") {
          message.textContent = "That handle is taken. Try another.";
        } else {
          message.textContent = failureText(result);
        }
      }).catch(function () { save.setAttribute("aria-busy", "false"); message.textContent = TEXT.failed; });
    });
    host.appendChild(form);
  }

  function mountSignIn(host) {
    host.classList.add("papyrus-reader-signin");
    var shown = "";
    subscribe(function () {
      var next = state.identity === "signed-in" ? (state.me && state.me.handle ? "member" : "handle") : state.identity;
      var signature = next === "member" ? next + "|" + state.me.handle + "|" + state.me.karma : next;
      if (signature === shown) return;
      shown = signature;
      host.textContent = "";
      if (next === "loading") {
        host.appendChild(element("span", "papyrus-reader-status", TEXT.loading));
      } else if (next === "unavailable") {
        host.appendChild(element("span", "papyrus-reader-status", TEXT.unavailable));
      } else if (next === "error") {
        host.appendChild(element("span", "papyrus-reader-status", TEXT.failed));
      } else if (next === "signed-out") {
        /* A form button, not a link: the endpoint is for machines (it answers 303 to Google), and people are never sent to an /api URL. */
        var signInForm = element("form");
        signInForm.method = "post";
        signInForm.action = settings.signIn;
        var returnTo = element("input");
        returnTo.type = "hidden";
        returnTo.name = "returnTo";
        returnTo.value = location.pathname + location.search;
        var signInButton = element("button", "papyrus-reader-button", "Sign in");
        signInButton.type = "submit";
        signInForm.appendChild(returnTo);
        signInForm.appendChild(signInButton);
        host.appendChild(signInForm);
        if (signInProblem) {
          var problemLine = element("span", "papyrus-reader-status", signInProblem);
          if (signInProblemCode) problemLine.appendChild(element("small", "papyrus-reader-status-code", " (code: " + signInProblemCode + ")"));
          host.appendChild(problemLine);
        }
      } else if (next === "handle") {
        handleForm(host);
      } else {
        host.appendChild(element("span", "papyrus-reader-handle", state.me.handle));
        host.appendChild(element("span", "papyrus-reader-karma", "Karma " + (Number(state.me.karma) || 0)));
        var form = element("form");
        form.method = "post";
        form.action = settings.signOut;
        var out = element("button", "papyrus-reader-button", "Sign out");
        out.type = "submit";
        form.appendChild(out);
        host.appendChild(form);
      }
    });
    requestMe();
  }

  var DRAFT_KEY = "papyrus-reader-submit-draft";
  var SIMILAR_HOURS = 48;

  function storage() {
    try { return window.localStorage; } catch (error) { return null; }
  }

  function readDraft() {
    try {
      var store = storage();
      var parsed = store ? JSON.parse(store.getItem(DRAFT_KEY) || "null") : null;
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (error) { return null; }
  }

  function writeDraft(draft) {
    try {
      var store = storage();
      if (!store) return;
      if (draft) store.setItem(DRAFT_KEY, JSON.stringify(draft)); else store.removeItem(DRAFT_KEY);
    } catch (error) {}
  }

  function guessCanonical(text) {
    try {
      var url = new URL(text.trim());
      if (url.protocol !== "http:" && url.protocol !== "https:") return null;
      url.hash = "";
      return url.href;
    } catch (error) { return null; }
  }

  function loadSubmissions() {
    return fetch(settings.base + "_data/reader/submissions.json", { credentials: "omit", cache: "no-cache" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (body) { return body && Array.isArray(body.submissions) ? body.submissions : []; })
      .catch(function () { return []; });
  }

  function field(form, labelText, control, hintText) {
    var wrapper = element("div", "papyrus-reader-field");
    control.id = "papyrus-reader-" + control.name + "-" + Math.random().toString(36).slice(2);
    var label = element("label", "papyrus-reader-field-label", labelText);
    label.setAttribute("for", control.id);
    wrapper.appendChild(label);
    wrapper.appendChild(control);
    if (hintText) wrapper.appendChild(element("span", "papyrus-reader-hint", hintText));
    form.appendChild(wrapper);
    return wrapper;
  }

  function mountSubmit(host, props) {
    var kinds = Array.isArray(props.kinds) && props.kinds.length ? props.kinds : ["link"];
    requestMe();
    host.classList.add("papyrus-reader-submit");
    var form = element("form", "papyrus-reader-submit-form");
    form.noValidate = false;
    var url = element("input", "papyrus-reader-input");
    url.type = "url"; url.name = "url"; url.required = true; url.maxLength = 2048; url.autocomplete = "off"; url.placeholder = "https://";
    var title = element("input", "papyrus-reader-input");
    title.type = "text"; title.name = "title"; title.required = true; title.maxLength = 200; title.autocomplete = "off";
    var note = element("textarea", "papyrus-reader-input");
    note.name = "note"; note.maxLength = 500; note.rows = 3;
    field(form, "Link", url);
    field(form, "Title", title);
    var kindInputs = [];
    if (kinds.length > 1) {
      var set = element("fieldset", "papyrus-reader-kinds");
      set.appendChild(element("legend", "papyrus-reader-field-label", "Kind"));
      kinds.forEach(function (kind, index) {
        var label = element("label", "papyrus-reader-kind");
        var radio = element("input");
        radio.type = "radio"; radio.name = "kind"; radio.value = kind; radio.checked = index === 0;
        label.appendChild(radio);
        label.appendChild(document.createTextNode(" " + kind));
        set.appendChild(label);
        kindInputs.push(radio);
      });
      form.appendChild(set);
    }
    field(form, "Note (optional)", note, "Up to 500 characters of plain text. Everyone can read it.");
    var warning = element("p", "papyrus-reader-warning");
    warning.setAttribute("role", "status");
    warning.setAttribute("aria-live", "polite");
    var draftNote = element("p", "papyrus-reader-hint", "Saved locally: a draft of this form is kept in this browser only, never sent anywhere, and cleared when you submit.");
    var send = element("button", "papyrus-reader-button", "Submit link");
    send.type = "submit";
    var status = element("p", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    var result = element("div", "papyrus-reader-submit-result");
    [warning, draftNote, send, status].forEach(function (node) { form.appendChild(node); });
    host.appendChild(form);
    host.appendChild(result);

    function chosenKind() {
      var picked = kindInputs.filter(function (radio) { return radio.checked; })[0];
      return picked ? picked.value : kinds[0];
    }

    var draft = readDraft();
    if (draft) {
      url.value = String(draft.url || ""); title.value = String(draft.title || ""); note.value = String(draft.note || "");
      kindInputs.forEach(function (radio) { radio.checked = radio.value === draft.kind; });
      if (kindInputs.length && !kindInputs.some(function (radio) { return radio.checked; })) kindInputs[0].checked = true;
    }
    var saveTimer = null;
    function saveDraft() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(function () {
        writeDraft(url.value || title.value || note.value ? { url: url.value, title: title.value, note: note.value, kind: chosenKind() } : null);
      }, 300);
    }
    [url, title, note].forEach(function (control) { control.addEventListener("input", saveDraft); });
    kindInputs.forEach(function (radio) { radio.addEventListener("change", saveDraft); });

    var known = [];
    function showWarning() {
      var canonical = guessCanonical(url.value);
      warning.textContent = "";
      if (!canonical) return;
      var same = known.filter(function (row) { return row.url === canonical; })[0];
      if (same) {
        warning.textContent = "Warning: this link may already be submitted as \u201c" + same.title + "\u201d. You can still submit it; the site checks again.";
        return;
      }
      var host_ = new URL(canonical).hostname;
      var since = Date.now() - SIMILAR_HOURS * 3600 * 1000;
      var recent = known.filter(function (row) { return row.domain === host_ && Date.parse(row.createdAt) >= since; });
      if (recent.length) warning.textContent = "Heads up: " + plural(recent.length, "link", "links") + " from " + host_ + " " + (recent.length === 1 ? "was" : "were") + " submitted in the last " + SIMILAR_HOURS + " hours. Check that yours is not the same story.";
    }
    loadSubmissions().then(function (rows) { known = rows; showWarning(); });
    url.addEventListener("input", showWarning);
    url.addEventListener("change", showWarning);

    var message = "";
    var busy = false;
    subscribe(function () {
      var disabled = !enabled();
      [url, title, note, send].concat(kindInputs).forEach(function (control) { control.disabled = disabled; });
      send.setAttribute("aria-busy", busy ? "true" : "false");
      status.textContent = message || controlStatus();
    });

    function showSuccess(body) {
      result.textContent = "";
      if (body.state === "held") {
        result.appendChild(element("p", "papyrus-reader-pending", "Held for review \u2014 a moderator reads it before it is public."));
      } else {
        result.appendChild(element("p", "papyrus-reader-pending", "Pending \u2014 we\u2019re reading the link."));
        result.appendChild(element("p", "papyrus-reader-hint", "Your submission is public now. Editors may promote it to a story."));
      }
      if (body.similar && body.similar.length) {
        result.appendChild(element("p", "papyrus-reader-warning", "Similar recent links from the same site:"));
        var list = element("ul", "papyrus-reader-similar");
        body.similar.forEach(function (row) {
          var item = element("li");
          var link = element("a", "papyrus-reader-link", row.title);
          link.href = row.url; link.rel = "noopener noreferrer nofollow";
          item.appendChild(link);
          list.appendChild(item);
        });
        result.appendChild(list);
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!enabled() || busy) return;
      busy = true;
      message = "";
      result.textContent = "";
      notify();
      var body = { url: url.value, title: title.value, kind: chosenKind() };
      if (note.value.trim()) body.note = note.value;
      post("/submit", body).then(function (answer) {
        busy = false;
        if (answer.ok) {
          clearTimeout(saveTimer);
          writeDraft(null);
          form.reset();
          kindInputs.forEach(function (radio, index) { radio.checked = index === 0; });
          showWarning();
          showSuccess(answer.body);
        } else if (answer.status === 409 && answer.body.error === "duplicate_submission") {
          var existing = answer.body.existing;
          message = existing ? "Already submitted as \u201c" + existing.title + "\u201d (" + existing.state + ")." : "That link was already submitted.";
        } else if (answer.status === 422 && answer.body.error === "handle_required") {
          message = "Choose a handle first, using the sign-in control, then submit again.";
        } else {
          message = failureText(answer);
        }
        notify();
      }).catch(function () { busy = false; message = TEXT.failed; notify(); });
    });
  }

  // Comments. Reads <base>_data/reader/comments/<subject>.json; the reader's own new, edited and deleted comments show at once
  // from local copies until a newer file arrives.
  var localComments = {};

  function localFor(subject) {
    return (localComments[subject] = localComments[subject] || { added: {}, overrides: {} });
  }

  function rememberComment(subject, created) {
    var local = localFor(subject);
    local.added[created.id] = {
      id: created.id, readerId: state.me ? state.me.readerId : "", handle: state.me ? state.me.handle : "", body: created.body,
      createdAt: created.createdAt, parent: created.parent || null, edited: false, held: created.state === "held", at: Date.now()
    };
    notify();
  }

  function commentTime(createdAt) {
    var seconds = Math.max(0, (Date.now() - Date.parse(createdAt)) / 1000);
    if (isNaN(seconds)) return "";
    if (seconds < 60) return "just now";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return plural(minutes, "minute", "minutes") + " ago";
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return plural(hours, "hour", "hours") + " ago";
    return plural(Math.floor(hours / 24), "day", "days") + " ago";
  }

  function mergeComments(subject, fetched) {
    var local = localFor(subject);
    var generated = fetched ? Date.parse(fetched.generatedAt) : 0;
    var entries = (fetched && fetched.comments ? fetched.comments : []).map(function (entry) { return Object.assign({}, entry); });
    var known = {};
    entries.forEach(function (entry) { known[entry.id] = entry; });
    Object.keys(local.overrides).forEach(function (id) {
      var override = local.overrides[id];
      if (generated >= override.at) { delete local.overrides[id]; return; }
      var entry = known[id];
      if (!entry) return;
      if (override.deleted) { entry.stub = true; entry.parent = null; delete entry.body; delete entry.handle; delete entry.readerId; }
      else if (override.body !== undefined) { entry.body = override.body; entry.edited = true; }
    });
    Object.keys(local.added).forEach(function (id) {
      if (known[id] || generated >= local.added[id].at) { if (known[id]) delete local.added[id]; return; }
      entries.push(Object.assign({}, local.added[id]));
    });
    entries.sort(function (left, right) { return Date.parse(left.createdAt) - Date.parse(right.createdAt); });
    return entries;
  }

  function commentForm(options) {
    var form = element("form", "papyrus-reader-comment-form");
    var input = element("textarea", "papyrus-reader-input");
    input.name = "body"; input.rows = options.rows || 3; input.maxLength = options.maximumLength; input.required = true;
    input.id = "papyrus-reader-comment-" + Math.random().toString(36).slice(2);
    var label = element("label", "papyrus-reader-field-label", options.label);
    label.setAttribute("for", input.id);
    var counter = element("span", "papyrus-reader-hint");
    var send = element("button", "papyrus-reader-button", options.button);
    send.type = "submit";
    var status = element("span", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    [label, input, counter, send, status].forEach(function (node) { form.appendChild(node); });
    var key = options.draftKey;
    if (key && options.drafts[key] !== undefined) input.value = options.drafts[key]; else if (options.value) input.value = options.value;
    function count() { counter.textContent = plural(options.maximumLength - input.value.length, "character", "characters") + " left"; }
    input.addEventListener("input", function () { if (key) options.drafts[key] = input.value; count(); });
    count();
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!enabled() || send.getAttribute("aria-busy") === "true" || !input.value.trim()) return;
      send.setAttribute("aria-busy", "true");
      status.textContent = "";
      options.submit(input.value).then(function (failure) {
        send.setAttribute("aria-busy", "false");
        if (failure) { status.textContent = failure; return; }
        input.value = "";
        if (key) delete options.drafts[key];
        count();
        if (options.done) options.done();
      }).catch(function () { send.setAttribute("aria-busy", "false"); status.textContent = TEXT.failed; });
    });
    return { form: form, input: input, send: send, status: status, refresh: function () { input.disabled = !enabled(); send.disabled = !enabled(); } };
  }

  // A report goes to the moderation queue. One button that opens a short form; every state is words.
  function reportControl(target) {
    var wrapper = element("span", "papyrus-reader-report");
    var open = element("button", "papyrus-reader-button", "Report");
    open.type = "button";
    open.setAttribute("aria-expanded", "false");
    var form = element("form", "papyrus-reader-report-form");
    form.hidden = true;
    var input = element("input", "papyrus-reader-input");
    input.type = "text"; input.name = "reason"; input.required = true; input.maxLength = 500; input.autocomplete = "off";
    input.id = "papyrus-reader-report-" + Math.random().toString(36).slice(2);
    var label = element("label", "papyrus-reader-field-label", "Why are you reporting this?");
    label.setAttribute("for", input.id);
    var send = element("button", "papyrus-reader-button", "Send report");
    send.type = "submit";
    var status = element("span", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    [label, input, send].forEach(function (node) { form.appendChild(node); });
    wrapper.appendChild(open);
    wrapper.appendChild(form);
    wrapper.appendChild(status);
    open.addEventListener("click", function () {
      form.hidden = !form.hidden;
      open.setAttribute("aria-expanded", form.hidden ? "false" : "true");
      if (!form.hidden) input.focus();
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!input.value.trim() || send.getAttribute("aria-busy") === "true") return;
      send.setAttribute("aria-busy", "true");
      status.textContent = "";
      post("/report", { target: target, reason: input.value }).then(function (result) {
        send.setAttribute("aria-busy", "false");
        if (result.ok) {
          form.hidden = true;
          open.hidden = true;
          status.textContent = "Reported. A moderator will look at it.";
        } else {
          status.textContent = failureText(result);
        }
      }).catch(function () { send.setAttribute("aria-busy", "false"); status.textContent = TEXT.failed; });
    });
    return { node: wrapper };
  }

  function mountReport(host, props) {
    requestMe();
    var control = reportControl(props.target);
    var open = control.node.querySelector("button");
    host.appendChild(control.node);
    subscribe(function () { open.disabled = !enabled(); });
  }

  function mountComments(host, props) {
    var subject = props.subject;
    var maximumLength = Number(props.maximumLength) || 2000;
    var editMinutes = props.editMinutes === undefined ? 10 : Number(props.editMinutes);
    requestMe(subject);
    host.classList.add("papyrus-reader-comments");
    var heading = element("p", "papyrus-reader-comment-count");
    var list = element("ol", "papyrus-reader-comment-list");
    var status = element("p", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    var drafts = {};
    var fetched = null;
    var replying = null;
    var editing = null;
    var message = "";
    var url = settings.base + "_data/reader/comments/" + encodeURIComponent(subject) + ".json";
    var main = commentForm({
      label: "Add a comment", button: "Post comment", maximumLength: maximumLength,
      submit: function (body) {
        return post("/comment", { subject: subject, body: body }).then(function (result) {
          if (!result.ok) return failureText(result);
          rememberComment(subject, result.body);
          return "";
        });
      }
    });
    main.form.classList.add("papyrus-reader-comment-main");
    host.appendChild(heading);
    host.appendChild(list);
    host.appendChild(status);
    host.appendChild(main.form);

    function load() {
      return fetch(url, { credentials: "omit", cache: "no-cache" })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (body) { if (body && Array.isArray(body.comments)) { fetched = body; notify(); } })
        .catch(function () {});
    }

    function write(path, payload, apply) {
      message = "";
      return post(path, payload).then(function (result) {
        if (result.ok) { apply(result.body); return ""; }
        message = failureText(result);
        notify();
        return message;
      }).catch(function () { message = TEXT.failed; notify(); return message; });
    }

    function renderComment(entry, children, depth) {
      var item = element("li", "papyrus-reader-comment");
      item.setAttribute("data-comment-id", entry.id);
      if (entry.stub) {
        item.appendChild(element("p", "papyrus-reader-comment-removed", "This comment was removed."));
      } else {
        var meta = element("p", "papyrus-reader-comment-meta");
        meta.appendChild(element("span", "papyrus-reader-handle", entry.handle || "A reader"));
        meta.appendChild(document.createTextNode(" \u00b7 " + commentTime(entry.createdAt) + (entry.edited ? " (edited)" : "") + (entry.held ? " \u2014 held for review, only you can see it" : "")));
        item.appendChild(meta);
        var own = state.me && entry.readerId && entry.readerId === state.me.readerId;
        if (editing === entry.id) {
          var editForm = commentForm({
            label: "Edit your comment", button: "Save", maximumLength: maximumLength, drafts: drafts, draftKey: "edit-" + entry.id, value: entry.body,
            submit: function (body) {
              return write("/comment/edit", { id: entry.id, body: body }, function () {
                localFor(subject).overrides[entry.id] = { body: body, at: Date.now() };
                editing = null;
                notify();
              });
            }
          });
          editForm.refresh();
          var cancel = element("button", "papyrus-reader-button", "Cancel");
          cancel.type = "button";
          cancel.addEventListener("click", function () { editing = null; notify(); });
          editForm.form.appendChild(cancel);
          item.appendChild(editForm.form);
        } else {
          var body = element("p", "papyrus-reader-comment-body", entry.body);
          item.appendChild(body);
          var actions = element("p", "papyrus-reader-comment-actions");
          if (depth === 0 && enabled()) {
            var reply = element("button", "papyrus-reader-button", "Reply");
            reply.type = "button";
            reply.setAttribute("aria-expanded", replying === entry.id ? "true" : "false");
            reply.addEventListener("click", function () { replying = replying === entry.id ? null : entry.id; notify(); });
            actions.appendChild(reply);
          }
          if (own && enabled()) {
            if (editMinutes > 0 && Date.now() - Date.parse(entry.createdAt) < editMinutes * 60000) {
              var edit = element("button", "papyrus-reader-button", "Edit");
              edit.type = "button";
              edit.addEventListener("click", function () { editing = entry.id; notify(); });
              actions.appendChild(edit);
            }
            var remove = element("button", "papyrus-reader-button", "Delete");
            remove.type = "button";
            remove.addEventListener("click", function () {
              write("/comment/delete", { id: entry.id }, function () {
                var local = localFor(subject);
                delete local.added[entry.id];
                local.overrides[entry.id] = { deleted: true, at: Date.now() };
                notify();
              });
            });
            actions.appendChild(remove);
          }
          if (!own && enabled() && !entry.held) actions.appendChild(reportControl(entry.id).node);
          if (actions.childNodes.length) item.appendChild(actions);
        }
      }
      if (replying === entry.id && enabled()) {
        var replyForm = commentForm({
          label: "Your reply", button: "Post reply", maximumLength: maximumLength, rows: 2, drafts: drafts, draftKey: "reply-" + entry.id,
          submit: function (body) {
            return post("/comment", { subject: subject, body: body, parent: entry.id }).then(function (result) {
              if (!result.ok) return failureText(result);
              rememberComment(subject, result.body);
              replying = null;
              return "";
            });
          }
        });
        item.appendChild(replyForm.form);
      }
      if (children.length) {
        var nested = element("ol", "papyrus-reader-comment-list papyrus-reader-replies");
        children.forEach(function (child) { nested.appendChild(renderComment(child, [], 1)); });
        item.appendChild(nested);
      }
      return item;
    }

    subscribe(function () {
      var entries = mergeComments(subject, fetched);
      var count = entries.filter(function (entry) { return !entry.stub; }).length;
      var prerendered = !fetched && props.count !== undefined ? Number(props.count) : count;
      heading.textContent = plural(prerendered, "comment", "comments");
      var repliesOf = {};
      entries.forEach(function (entry) { if (entry.parent) (repliesOf[entry.parent] = repliesOf[entry.parent] || []).push(entry); });
      var present = {};
      entries.forEach(function (entry) { present[entry.id] = true; });
      var focused = document.activeElement;
      var keepFocus = focused && host.contains(focused) && (focused.tagName === "TEXTAREA" || focused.tagName === "INPUT");
      if (keepFocus && focused.closest(".papyrus-reader-comment-form") && list.contains(focused)) {
        // Do not rebuild under someone who is typing a reply or an edit; the next change will catch up.
        main.refresh();
        status.textContent = message || controlStatus();
        return;
      }
      list.textContent = "";
      entries.filter(function (entry) { return !entry.parent || !present[entry.parent]; }).forEach(function (entry) {
        list.appendChild(renderComment(entry, repliesOf[entry.id] || [], 0));
      });
      main.refresh();
      status.textContent = message || controlStatus();
    });
    load();
    setInterval(function () { if (document.visibilityState === "visible") load(); }, settings.pollSeconds * 1000);
  }

  var RANKED_LISTS = { front: true, rising: true, "new": true };

  function safeHref(url) {
    var text = typeof url === "string" ? url : "";
    return /^\/(?!\/)/.test(text) || /^https?:\/\//i.test(text) ? text : "";
  }

  function hoursText(hours) {
    return (Math.round(hours * 10) / 10) + " h";
  }

  function agoShort(timestamp) {
    var minutes = Math.floor(Math.max(0, Date.now() - Date.parse(timestamp)) / 60000);
    if (isNaN(minutes)) return "";
    if (minutes < 1) return "just now";
    if (minutes < 60) return minutes + " min ago";
    var hours = Math.floor(minutes / 60);
    return hours < 48 ? hours + " h ago" : Math.floor(hours / 24) + " d ago";
  }

  function rankedFigure(list, row, board) {
    if (list === "rising") {
      var span = board.parameters && board.parameters.risingWindowHours;
      return plural(row.upvotes, "upvote", "upvotes") + (span ? " in " + hoursText(span) : "");
    }
    if (list === "front") return "Score " + (Math.round(row.score * 100) / 100);
    return agoShort(row.at);
  }

  function renderRankedRow(list, row, entry, board, rank) {
    var item = element("li", "papyrus-reader-ranked-row");
    item.appendChild(element("span", "papyrus-reader-ranked-rank", rank + "."));
    var link = element("a", "papyrus-reader-link papyrus-reader-ranked-title", entry.title || row.subject);
    var href = safeHref(entry.url);
    if (href) link.setAttribute("href", href);
    if (entry.kind === "submission") link.setAttribute("rel", "nofollow noopener noreferrer ugc");
    item.appendChild(link);
    var where = entry.kind === "submission" ? entry.domain : entry.section;
    if (where) item.appendChild(element("span", "papyrus-reader-ranked-where", where));
    if (entry.kind === "submission" && entry.state === "pending") item.appendChild(element("span", "papyrus-reader-pending", "Pending"));
    var figure = rankedFigure(list, row, board);
    if (figure) item.appendChild(element("span", "papyrus-reader-ranked-figure", figure));
    return item;
  }

  function mountRankedList(host, props) {
    var list = RANKED_LISTS[props.list] ? props.list : "front";
    var limit = Math.floor(Number(props.limit)) > 0 ? Math.floor(Number(props.limit)) : 10;
    var emptyText = typeof props.empty === "string" && props.empty ? props.empty : "Nothing here yet.";
    var data = null;
    var failed = false;
    host.classList.add("papyrus-reader-ranked");
    var body = element("div", "papyrus-reader-ranked-body");
    var stamp = element("p", "papyrus-reader-freshness papyrus-reader-ranked-updated");
    host.appendChild(body);
    host.appendChild(stamp);

    function render() {
      body.textContent = "";
      stamp.textContent = "";
      if (!data) {
        body.appendChild(element("p", "papyrus-reader-ranked-message", failed ? "This list could not be loaded. Try again later." : "Loading the list"));
        return;
      }
      var rows = (data.board[list] || []).map(function (row) { return { row: row, entry: data.subjects[row.subject] }; })
        .filter(function (pair) { return pair.entry && (!props.section || pair.entry.section === props.section); })
        .slice(0, limit);
      if (!rows.length) {
        body.appendChild(element("p", "papyrus-reader-ranked-empty", emptyText));
      } else {
        var ordered = element("ol", "papyrus-reader-ranked-list");
        ordered.setAttribute("role", "list");
        rows.forEach(function (pair, index) { ordered.appendChild(renderRankedRow(list, pair.row, pair.entry, data.board, index + 1)); });
        body.appendChild(ordered);
      }
      var time = element("time", "", ago(data.board.generatedAt));
      time.setAttribute("datetime", data.board.generatedAt);
      stamp.appendChild(time);
    }

    function fetchJson(name) {
      return fetch(settings.base + "_data/reader/" + name, { credentials: "omit", cache: "no-cache" })
        .then(function (response) { if (!response.ok) throw new Error(name); return response.json(); });
    }

    function load() {
      return Promise.all([fetchJson("board.json"), fetchJson("subjects.json")]).then(function (files) {
        data = { board: files[0], subjects: files[1].subjects || {} };
        failed = false;
        render();
      }).catch(function () {
        failed = true;
        if (!data) render();
      });
    }

    render();
    load();
    setInterval(function () { if (document.visibilityState === "visible") load(); }, settings.pollSeconds * 1000);
    setInterval(function () { if (document.visibilityState === "visible" && data) render(); }, 30000);
  }

  var islands = { RankedList: mountRankedList, ReaderSignIn: mountSignIn, Comments: mountComments, Report: mountReport, Submit: mountSubmit, Vote: mountVote, Flag: mountFlag, UsedIt: mountUsedIt, Rating: mountRating, Freshness: mountFreshness };
  var started = false;

  function guarded(mount) {
    return function (host, props) {
      if (host.papyrusReaderMounted) return;
      host.papyrusReaderMounted = true;
      if (!started) { started = true; startPolling(); }
      mount(host, props || parseProps(host));
    };
  }

  var registry = window.papyrusIslands = window.papyrusIslands || {};
  var guardedIslands = {};
  Object.keys(islands).forEach(function (name) {
    guardedIslands[name] = guarded(islands[name]);
    registry[name] = guardedIslands[name];
  });

  function mountAll() {
    document.querySelectorAll("[data-island]").forEach(function (host) {
      var mount = guardedIslands[host.getAttribute("data-island")];
      if (!mount || host.papyrusReaderMounted) return;
      mount(host, parseProps(host));
      var summary = host.querySelector(":scope > .papyrus-island-summary");
      if (summary) summary.remove();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountAll); else mountAll();
})();
