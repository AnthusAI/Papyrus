/*
 * The notifications plugin's reader pages (/notifications/confirm/, /confirmed/, /preferences/, /unsubscribe/, /unsubscribed/, /expired/).
 *
 * The pages are static HTML in the site's own chrome. This script, loaded by those pages only, makes them work:
 *   - it reads `token`, `list`, `lists`, `msg` and `step` from the query string and fills the hidden `t` (and `l`) fields of the forms, which
 *     post to the machine endpoints under /api/notifications/ and come back to a clean page;
 *   - it asks GET /api/notifications/state (JSON) for the names of lists and, for the preferences page, the subscriber's state;
 *   - when a link is no good it replaces the page with the site's expired page; when the service cannot be reached it says so in words.
 *     People are never sent to an /api URL.
 * Each list on the preferences page is a button that is On or Off, said in words and shown with a Lucide bell or bell-off (never colour alone).
 * No inline script or style: it works under a strict CSP. Without JavaScript the pages show a short note and no form.
 */
(function () {
  "use strict";

  var TOKEN = /^[A-Za-z0-9._-]{1,2048}$/;
  var LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;
  var STATE = "/api/notifications/state";
  var NOTICES = { saved: "Your choices are saved.", unsubscribed: "You are unsubscribed from everything." };
  var SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" data-icon="';
  var BELL = SVG + 'bell"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/></svg>';
  var BELL_OFF = SVG + 'bell-off"><path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/></svg>';

  function one(root, selector) { return root.querySelector(selector); }
  function show(node, visible) { if (node) node.hidden = !visible; }
  function make(tag, text) { var node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; }

  function listIds(value) {
    return (value || "").split(",").map(function (id) { return id.trim(); }).filter(function (id) { return LIST_ID.test(id); });
  }

  function expired(root) { window.location.replace(root.getAttribute("data-expired-href") || "/"); }

  function unavailable(root) {
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

  // One button per list. Pressed means On. The state is a word and an icon, and the hidden field is sent only while the list is On.
  function listRow(entry, index) {
    var row = make("div");
    row.className = "markus-notifications-list";
    var field = document.createElement("input");
    field.type = "hidden";
    field.name = "l";
    field.value = entry.id;
    var button = make("button");
    button.type = "button";
    button.className = "markus-notifications-toggle";
    button.id = "notifications-list-" + index;
    var mark = make("span");
    mark.className = "markus-notifications-mark";
    var name = make("span", entry.name);
    name.className = "markus-notifications-name";
    var word = make("span");
    word.className = "markus-notifications-state";
    button.appendChild(mark);
    button.appendChild(name);
    button.appendChild(word);
    function paint(on) {
      button.setAttribute("aria-pressed", on ? "true" : "false");
      mark.innerHTML = on ? BELL : BELL_OFF;
      word.textContent = on ? "On" : "Off";
      field.disabled = !on;
    }
    button.addEventListener("click", function () { paint(button.getAttribute("aria-pressed") !== "true"); });
    paint(entry.subscribed === true);
    row.appendChild(field);
    row.appendChild(button);
    if (entry.description) row.appendChild(make("p", entry.description));
    return row;
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
      getState("kind=preferences&t=" + encodeURIComponent(token)).then(function (answer) {
        if (!answer.ok || answer.body.status !== "ready") return failed(root, answer);
        var manage = one(root, "[data-notifications-section=manage]");
        var form = one(manage, "form");
        var holder = one(form, "[data-notifications-lists]");
        var lists = answer.body.lists || [];
        one(manage, "[data-notifications-email]").textContent = "Notifications for " + (answer.body.email || "your address") + ". Press a button to turn it on or off, then save.";
        lists.forEach(function (entry, index) { holder.appendChild(listRow(entry, index)); });
        var confirm = one(root, "[data-notifications-section=delete]");
        fillToken(form, token);
        one(confirm, "form").elements.t.value = token;
        show(one(confirm, "form"), true);
        one(confirm, "[data-notifications-back]").href = root.getAttribute("data-preferences-href") + "?token=" + encodeURIComponent(token);
        show(step === "delete" ? confirm : manage, true);
        if (NOTICES[message] && step !== "delete") {
          var notice = one(root, "[data-notifications-notice]");
          one(notice, "span").textContent = NOTICES[message] + (message === "saved" ? summary(lists) : "");
          show(notice, true);
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
