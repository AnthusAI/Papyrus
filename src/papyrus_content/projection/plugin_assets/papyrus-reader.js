/*
 * Reader islands for a static Papyrus site (the reader-steering plugin, contract 1).
 *
 * Framework-free and dependency-free. Load it once, beside the islands runtime:
 *   <script src="/_plugins/papyrus-reader@1.js" defer></script>
 *   <link rel="stylesheet" href="/_plugins/papyrus-reader@1.css">
 * and place mount points where the site owns the HTML (an article template, the header):
 *   <div data-island="ReaderSignIn"></div>
 *   <div data-island="Vote" data-props='{"subject":"<item key>","up":3}'></div>
 *   <div data-island="UsedIt" data-props='{"subject":"<item key>","usedIt":1}'></div>
 *   <div data-island="Rating" data-props='{"subject":"<item key>","dimensions":["real","useful"]}'></div>
 *   <div data-island="Freshness" data-props='{"generatedAt":"2026-10-21T10:00:00Z"}'></div>
 *   <div data-island="Submit" data-props='{"kinds":["article","tool"]}'></div>   (the /submit/ page)
 *
 * The script registers its islands in window.papyrusIslands and also mounts any [data-island] of its own names, once, so
 * it works with or without the core islands runtime. Props prerender the last snapshot values; the page then fetches
 * <base>_data/reader/items.json, refetches it every 60 seconds while the tab is visible, and asks /api/reader/me
 * for the reader's own votes. Site settings: window.papyrusReader = { base: "/", api: "/api/reader", signIn: "...", signOut: "..." }.
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
  var SUBJECTS_PER_REQUEST = 50;
  var TEXT = {
    loading: "Checking sign-in",
    unavailable: "Reader sign-in is not open yet",
    signedOut: "Sign in to vote and rate",
    failed: "Something went wrong. Try again later.",
    notRated: "Not rated"
  };

  var state = { identity: "loading", me: null, snapshot: null, adjustments: {}, handleMessage: "" };
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

  function loadSnapshot() {
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

  function mountVote(host, props) {
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
      var editor = element("span", "papyrus-reader-stats");
      group.insertBefore(label, group.firstChild);
      group.appendChild(own);
      group.appendChild(readers);
      group.appendChild(editor);
      host.appendChild(group);
      return { dimension: dimension, buttons: buttons, own: own, readers: readers, editor: editor, busy: false };
    });
    var status = element("p", "papyrus-reader-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    host.appendChild(status);
    var message = "";
    subscribe(function () {
      var item = snapshotItem(subject);
      var prerendered = props.ratings || {};
      rows.forEach(function (row) {
        var published = state.snapshot ? item && item.ratings && item.ratings[row.dimension] : prerendered[row.dimension];
        var value = mine(subject, row.dimension);
        row.buttons.forEach(function (button, index) {
          button.setAttribute("aria-pressed", value === index + 1 ? "true" : "false");
          button.disabled = !enabled();
          button.setAttribute("aria-busy", row.busy ? "true" : "false");
        });
        row.own.textContent = value ? "Your rating: " + value + " of 5" : TEXT.notRated;
        row.readers.textContent = "Readers: " + statsText(published && published.reader);
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
        var link = element("a", "papyrus-reader-link", "Sign in");
        link.href = settings.signIn + "?returnTo=" + encodeURIComponent(location.pathname + location.search);
        host.appendChild(link);
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
      result.appendChild(element("p", "papyrus-reader-pending", "Pending \u2014 we\u2019re reading the link."));
      result.appendChild(element("p", "papyrus-reader-hint", "Your submission is public now. Editors may promote it to a story."));
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

  var islands = { ReaderSignIn: mountSignIn, Submit: mountSubmit, Vote: mountVote, UsedIt: mountUsedIt, Rating: mountRating, Freshness: mountFreshness };
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
