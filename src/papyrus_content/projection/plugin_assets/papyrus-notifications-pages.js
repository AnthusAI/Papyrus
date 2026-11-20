/*
 * The notifications plugin's reader pages (/notifications/confirm/, /confirmed/, /preferences/, /unsubscribe/, /unsubscribed/, /expired/).
 *
 * The pages are static HTML in the site's own chrome. This script, loaded by those pages only, makes them work:
 *   - it reads `token`, `list`, `lists`, `msg` and `step` from the query string and fills the hidden `t` (and `l`) fields of the forms, which
 *     post to the machine endpoints under /api/notifications/ and come back to a clean page;
 *   - it asks GET /api/notifications/state (JSON) for the names of lists and, for the preferences page, the subscriber's state;
 *   - when a link is no good it replaces the page with the site's expired page; when the service cannot be reached it says so in words.
 *     People are never sent to an /api URL.
 * The preferences page shows each family of lists (the same items at different cadences: every new item, the daily summary) as one choice among its lists and Off,
 * and every other list as a button that is On or Off. A state is said in words and shown with a Lucide mark (a bell or bell-off, a circle-check or circle), never colour alone.
 * Choosing something in a family the reader does not hold shows the site's consent wording and posts it back as the evidence; the function then mails a confirmation and
 * the list begins only when the reader presses its link. A cadence chosen inside a family the reader holds needs nothing more.
 * On a site with a GA4 measurement id the analytics script (`papyrus-notifications-analytics-v1.js`) is loaded first and this script reports
 * subscribe_confirmed, preferences_changed, unsubscribe and subscribe_error through it (docs/site-hosting.md, "Subscription and notification
 * events"); the events carry list ids and the page type, never a token, address or query string. Without it nothing is reported.
 * No inline script or style: it works under a strict CSP. Without JavaScript the pages show a short note and no form.
 */
(function () {
  "use strict";

  var TOKEN = /^[A-Za-z0-9._-]{1,2048}$/;
  var LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;
  var STATE = "/api/notifications/state";
  var NOTICES = {
    saved: "Your choices are saved.",
    unsubscribed: "You are unsubscribed from everything.",
    check_email: "Check your email to finish."
  };
  var SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" data-icon="';
  var BELL = SVG + 'bell"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/></svg>';
  var BELL_OFF = SVG + 'bell-off"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/></svg>';

  var CHECK = SVG + 'circle-check"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>';
  var CIRCLE = SVG + 'circle"><circle cx="12" cy="12" r="10"/></svg>';

  function one(root, selector) { return root.querySelector(selector); }
  function show(node, visible) { if (node) node.hidden = !visible; }
  function make(tag, text) { var node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; }

  function listIds(value) {
    return (value || "").split(",").map(function (id) { return id.trim(); }).filter(function (id) { return LIST_ID.test(id); });
  }

  // Analytics is optional: the analytics script exists only on a site with a measurement id, and the page works without it.
  function report(name, params, onLoad) {
    var analytics = window.papyrusNotificationsAnalytics;
    if (!analytics) return;
    try { if (onLoad) analytics.trackLoad(name, params); else analytics.track(name, params); } catch (e) {}
  }

  function pageType(root) {
    var name = root.getAttribute("data-notifications-page");
    return name === "index" ? "subscribe" : name || "other";
  }

  function expired(root) { window.location.replace(root.getAttribute("data-expired-href") || "/"); }

  function unavailable(root) {
    report("subscribe_error", { page_type: pageType(root) });
    Array.prototype.forEach.call(root.querySelectorAll("form"), function (form) { show(form, false); });
    show(one(root, "[data-notifications-unavailable]"), true);
  }

  // A link that is no good (400) goes to the expired page; the service being down (502, 503) or the network failing is said in words.
  function getState(query) {
    return fetch(STATE + "?" + query, { credentials: "same-origin", cache: "no-store", headers: { accept: "application/json" } }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) { return { ok: response.ok, status: response.status, body: body || {} }; });
    });
  }

  function failed(root, answer) {
    if (answer.status === 502 || answer.status === 503) return unavailable(root);
    return expired(root);
  }

  function fillList(root, names) {
    var holder = one(root, "div[data-notifications-lists]");
    if (!holder || names.length === 0) return;
    var list = one(holder, "ul");
    names.forEach(function (name) { list.appendChild(make("li", name)); });
    show(holder, true);
  }

  function nameLists(ids) {
    if (ids.length === 0) return Promise.resolve([]);
    return getState("kind=lists&lists=" + encodeURIComponent(ids.join(","))).then(function (answer) {
      return (answer.body.lists || []).map(function (entry) { return entry.name; });
    }).catch(function () { return []; });
  }

  function fillToken(form, token) { form.elements.t.value = token; show(form, true); }

  function manageLink(root, token) {
    var holder = one(root, "p[data-notifications-manage]");
    if (!holder || !TOKEN.test(token)) return;
    var link = one(holder, "a");
    link.href = root.getAttribute("data-preferences-href") + "?token=" + encodeURIComponent(token);
    show(holder, true);
  }

  function field(name, value) {
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  }

  function button(className, id) {
    var node = make("button");
    node.type = "button";
    node.className = className;
    node.id = id;
    var mark = make("span");
    mark.className = "markus-notifications-mark";
    var word = make("span");
    word.className = "markus-notifications-state";
    return { node: node, mark: mark, word: word };
  }

  // A list that is its own family: one button, pressed means On. The state is a word and an icon, and the hidden field is sent only while the list is On.
  // `joining()` says whether the reader has turned on something they did not hold, which needs their consent.
  function listRow(entry, index) {
    var row = make("div");
    row.className = "markus-notifications-list";
    var hidden = field("l", entry.id);
    var control = button("markus-notifications-toggle", "notifications-list-" + index);
    var name = make("span", entry.name);
    name.className = "markus-notifications-name";
    control.node.appendChild(control.mark);
    control.node.appendChild(name);
    control.node.appendChild(control.word);
    var on = entry.subscribed === true;
    function paint() {
      control.node.setAttribute("aria-pressed", on ? "true" : "false");
      control.mark.innerHTML = on ? BELL : BELL_OFF;
      control.word.textContent = on ? "On" : "Off";
      hidden.disabled = !on;
    }
    control.node.addEventListener("click", function () { on = !on; paint(); row.changed(); });
    paint();
    row.appendChild(hidden);
    row.appendChild(control.node);
    if (entry.description) row.appendChild(make("p", entry.description));
    row.joining = function () { return on && entry.subscribed !== true; };
    return row;
  }

  // A family: the same items at different cadences. The reader holds one list of it or none, so it is one choice among its lists and Off.
  // The chosen one is pressed and says "Chosen"; the others say "Choose". Only the chosen list's hidden field is sent.
  function familyRow(entries, index) {
    var row = make("div");
    row.className = "markus-notifications-list markus-notifications-family";
    row.setAttribute("role", "group");
    var held = entries.filter(function (entry) { return entry.subscribed === true; })[0];
    var chosen = held ? held.id : "";
    var label = make("p", "Choose one: " + entries.map(function (entry) { return entry.name; }).join(", ") + ", or Off.");
    label.className = "markus-notifications-family-label";
    row.appendChild(label);
    var options = entries.map(function (entry) { return { id: entry.id, name: entry.name, description: entry.description }; });
    options.push({ id: "", name: "Off", description: "" });
    var painters = [];
    options.forEach(function (option, position) {
      var hidden = option.id ? field("l", option.id) : null;
      var control = button("markus-notifications-toggle markus-notifications-choice", "notifications-family-" + index + "-" + position);
      var name = make("span", option.name);
      name.className = "markus-notifications-name";
      control.node.appendChild(control.mark);
      control.node.appendChild(name);
      control.node.appendChild(control.word);
      function paint() {
        var on = chosen === option.id;
        control.node.setAttribute("aria-pressed", on ? "true" : "false");
        control.mark.innerHTML = on ? CHECK : CIRCLE;
        control.word.textContent = on ? "Chosen" : "Choose";
        if (hidden) hidden.disabled = !on;
      }
      control.node.addEventListener("click", function () {
        chosen = option.id;
        painters.forEach(function (repaint) { repaint(); });
        row.changed();
      });
      painters.push(paint);
      paint();
      if (hidden) row.appendChild(hidden);
      row.appendChild(control.node);
      if (option.description) row.appendChild(make("p", option.description));
    });
    row.joining = function () { return chosen !== "" && !held; };
    return row;
  }

  // Lists that name the same family are one choice; a list with no family is its own. The order is the site's.
  function arrange(lists) {
    var order = [];
    var members = {};
    lists.forEach(function (entry) {
      var family = entry.family || entry.id;
      if (!members[family]) { members[family] = []; order.push(family); }
      members[family].push(entry);
    });
    return order.map(function (family) { return members[family]; });
  }

  // Shows the site's consent wording and sends it with the save only while something the reader does not hold is chosen.
  function consentFor(root, form, wording, rows) {
    var block = one(root, "[data-notifications-consent]");
    var input = form.elements.consent;
    var action = one(form, "button[value=save] span");
    function update() {
      var needed = wording !== "" && rows.some(function (row) { return row.joining(); });
      input.value = needed ? wording : "";
      input.disabled = !needed;
      show(block, needed);
      if (needed) one(block, "[data-notifications-consent-words]").textContent = "Choosing this needs your confirmation. We will email you a link; it does not start until you press it. By saving you agree: " + wording;
      if (action) action.textContent = needed ? "Save and send a confirmation" : "Save";
    }
    rows.forEach(function (row) { row.changed = update; });
    update();
  }

  function summary(lists) {
    var on = lists.filter(function (entry) { return entry.subscribed === true; }).map(function (entry) { return entry.name; });
    var off = lists.filter(function (entry) { return entry.subscribed !== true; }).map(function (entry) { return entry.name; });
    return (on.length ? " You get: " + on.join(", ") + "." : " You get nothing.") + (off.length && on.length ? " You do not get: " + off.join(", ") + "." : "");
  }

  // The server redirects here only after the address is confirmed, so this page is the confirmed-success moment. Once per tab
  // session, and only with the token the confirmation redirect carries; the event itself carries no token, address or list.
  function reportSignUpOnce(token) {
    if (!TOKEN.test(token) || !window.papyrusAnalytics) return;
    try {
      if (window.sessionStorage.getItem("papyrus-sign-up-reported") === "1") return;
      window.sessionStorage.setItem("papyrus-sign-up-reported", "1");
    } catch (e) {}
    window.papyrusAnalytics.track("sign_up", { method: "notifications" });
  }

  var pages = {
    confirm: function (root, query) {
      var token = query.get("token") || "";
      if (!TOKEN.test(token)) return expired(root);
      getState("kind=confirm&t=" + encodeURIComponent(token)).then(function (answer) {
        if (!answer.ok || answer.body.status !== "ready") return failed(root, answer);
        fillList(root, (answer.body.lists || []).map(function (entry) { return entry.name; }));
        fillToken(one(root, "form"), token);
      }).catch(function () { unavailable(root); });
    },

    confirmed: function (root, query) {
      manageLink(root, query.get("token") || "");
      reportSignUpOnce(query.get("token") || "");
      if (TOKEN.test(query.get("token") || "")) report("subscribe_confirmed", { kind: listIds(query.get("lists")).join(","), page_type: "confirmed" }, true);
      return nameLists(listIds(query.get("lists"))).then(function (names) { fillList(root, names); });
    },

    unsubscribe: function (root, query) {
      var token = query.get("token") || "";
      var form = one(root, "form");
      if (!TOKEN.test(token)) return expired(root);
      var ids = listIds(query.get("list")).slice(0, 1);
      nameLists(ids).then(function (names) {
        var site = root.getAttribute("data-site-name") || "this site";
        form.elements.l.value = names.length > 0 ? ids[0] : "";
        if (names.length > 0) {
          one(root, "[data-notifications-prompt]").textContent = "Stop getting “" + names[0] + "” from " + site + "?";
          one(form, "button span").textContent = "Unsubscribe from this one";
        }
        fillToken(form, token);
        manageLink(root, token);
      });
    },

    unsubscribed: function (root, query) {
      manageLink(root, query.get("token") || "");
      if (TOKEN.test(query.get("token") || "")) report("unsubscribe", { kind: listIds(query.get("lists")).join(",") || "all", page_type: "unsubscribed" }, true);
      return nameLists(listIds(query.get("lists"))).then(function (names) { fillList(root, names); });
    },

    preferences: function (root, query) {
      var token = query.get("token") || "";
      var message = query.get("msg") || "";
      var step = query.get("step") || "";
      if (!TOKEN.test(token)) {
        if (message === "deleted") return show(one(root, "[data-notifications-section=deleted]"), true);
        return expired(root);
      }
      if (message === "unsubscribed") report("unsubscribe", { kind: "all", page_type: "preferences" }, true);
      getState("kind=preferences&t=" + encodeURIComponent(token)).then(function (answer) {
        if (!answer.ok || answer.body.status !== "ready") return failed(root, answer);
        var manage = one(root, "[data-notifications-section=manage]");
        var form = one(manage, "form");
        var holder = one(form, "[data-notifications-lists]");
        var lists = answer.body.lists || [];
        one(manage, "[data-notifications-email]").textContent = "Notifications for " + (answer.body.email || "your address") + ". Choose what you get, then save.";
        var rows = arrange(lists).map(function (entries, index) {
          var row = entries.length > 1 ? familyRow(entries, index) : listRow(entries[0], index);
          holder.appendChild(row);
          return row;
        });
        consentFor(root, form, typeof answer.body.consent === "string" ? answer.body.consent : "", rows);
        var confirm = one(root, "[data-notifications-section=delete]");
        fillToken(form, token);
        one(confirm, "form").elements.t.value = token;
        show(one(confirm, "form"), true);
        one(confirm, "[data-notifications-back]").href = root.getAttribute("data-preferences-href") + "?token=" + encodeURIComponent(token);
        show(step === "delete" ? confirm : manage, true);
        if (message === "saved" && step !== "delete") {
          var on = lists.filter(function (entry) { return entry.subscribed === true; }).map(function (entry) { return entry.id; });
          report("preferences_changed", { kind: on.join(","), page_type: "preferences" }, true);
        }
        if (NOTICES[message] && step !== "delete") {
          var notice = one(root, "[data-notifications-notice]");
          var words = NOTICES[message] + (message === "saved" || message === "check_email" ? summary(lists) : "");
          one(notice, "span").textContent = words;
          show(notice, true);
          // A new family waits for the reader's confirmation: say which, in words.
          if (message === "check_email") {
            nameLists(listIds(query.get("confirming"))).then(function (names) {
              if (names.length > 0) one(notice, "span").textContent = "Your other choices are saved. We emailed a link to confirm: " + names.join(", ") + ". It is not on until you press the link." + summary(lists);
            });
          }
        }
      }).catch(function () { unavailable(root); });
    }
  };

  function start() {
    var root = document.querySelector("[data-notifications-page]");
    if (!root) return;
    var page = pages[root.getAttribute("data-notifications-page")];
    if (page) page(root, new URLSearchParams(window.location.search));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
