/*
 * The newsletter plugin's human pages (/newsletter/confirm/, /confirmed/, /preferences/, /unsubscribe/, /unsubscribed/, /expired/).
 *
 * The pages are static HTML in the site's own chrome. This script, loaded by those pages only, makes them work:
 *   - it reads `token`, `list` and `lists` from the query string and fills the hidden `t` (and `l`) fields of the forms, which post to the
 *     machine endpoints under /api/newsletter/ and come back to a clean page;
 *   - it asks GET /api/newsletter/state (JSON) for the names of lists and, for the preferences page, the subscriber's state;
 *   - when a link is no good it replaces the page with the site's expired page. People are never sent to an /api URL.
 * No inline script or style: it works under a strict CSP. Without JavaScript the pages show a short note and no form.
 */
(function () {
  "use strict";

  var TOKEN = /^[A-Za-z0-9._-]{1,2048}$/;
  var LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;
  var STATE = "/api/newsletter/state";
  var NOTICES = { saved: "Your preferences are saved.", unsubscribed: "You are unsubscribed from everything." };

  function one(root, selector) { return root.querySelector(selector); }
  function show(node, visible) { if (node) node.hidden = !visible; }
  function make(tag, text) { var node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; }

  function listIds(value) {
    return (value || "").split(",").map(function (id) { return id.trim(); }).filter(function (id) { return LIST_ID.test(id); });
  }

  function expired(root) { window.location.replace(root.getAttribute("data-expired-href") || "/"); }

  function getState(query) {
    return fetch(STATE + "?" + query, { credentials: "same-origin", cache: "no-store", headers: { accept: "application/json" } }).then(function (response) {
      return response.json().then(function (body) { return { ok: response.ok, body: body || {} }; });
    });
  }

  function fillList(root, names) {
    var holder = one(root, "div[data-newsletter-lists]");
    if (!holder || names.length === 0) return;
    var list = one(holder, "ul");
    names.forEach(function (name) { list.appendChild(make("li", name)); });
    show(holder, true);
  }

  function nameLists(root, ids) {
    if (ids.length === 0) return Promise.resolve([]);
    return getState("kind=lists&lists=" + encodeURIComponent(ids.join(","))).then(function (answer) {
      return (answer.body.lists || []).map(function (entry) { return entry.name; });
    }).catch(function () { return []; });
  }

  function fillToken(form, token) { form.elements.t.value = token; show(form, true); }

  function manageLink(root, token) {
    var holder = one(root, "p[data-newsletter-manage]");
    if (!holder || !TOKEN.test(token)) return;
    var link = one(holder, "a");
    link.href = root.getAttribute("data-preferences-href") + "?token=" + encodeURIComponent(token);
    show(holder, true);
  }

  var pages = {
    confirm: function (root, query) {
      var token = query.get("token") || "";
      if (!TOKEN.test(token)) return expired(root);
      getState("kind=confirm&t=" + encodeURIComponent(token)).then(function (answer) {
        if (!answer.ok || answer.body.status !== "ready") return expired(root);
        fillList(root, (answer.body.lists || []).map(function (entry) { return entry.name; }));
        fillToken(one(root, "form"), token);
      }).catch(function () { expired(root); });
    },

    confirmed: function (root, query) {
      manageLink(root, query.get("token") || "");
      return nameLists(root, listIds(query.get("lists"))).then(function (names) { fillList(root, names); });
    },

    unsubscribe: function (root, query) {
      var token = query.get("token") || "";
      var form = one(root, "form");
      if (!TOKEN.test(token)) return expired(root);
      var ids = listIds(query.get("list")).slice(0, 1);
      nameLists(root, ids).then(function (names) {
        var site = root.getAttribute("data-site-name") || "this site";
        form.elements.l.value = names.length > 0 ? ids[0] : "";
        if (names.length > 0) {
          one(root, "[data-newsletter-prompt]").textContent = "Stop getting “" + names[0] + "” from " + site + "?";
          one(form, "button").textContent = "Unsubscribe from this list";
        }
        fillToken(form, token);
        manageLink(root, token);
      });
    },

    unsubscribed: function (root, query) {
      manageLink(root, query.get("token") || "");
      return nameLists(root, listIds(query.get("lists"))).then(function (names) { fillList(root, names); });
    },

    preferences: function (root, query) {
      var token = query.get("token") || "";
      var message = query.get("msg") || "";
      var step = query.get("step") || "";
      if (!TOKEN.test(token)) {
        if (message === "deleted") return show(one(root, "[data-newsletter-section=deleted]"), true);
        return expired(root);
      }
      getState("kind=preferences&t=" + encodeURIComponent(token)).then(function (answer) {
        if (!answer.ok || answer.body.status !== "ready") return expired(root);
        var manage = one(root, "[data-newsletter-section=manage]");
        var form = one(manage, "form");
        var holder = one(form, "[data-newsletter-lists]");
        one(manage, "[data-newsletter-email]").textContent = "Email preferences for " + (answer.body.email || "your address") + ". Tick the lists you want.";
        (answer.body.lists || []).forEach(function (entry, index) {
          var row = make("p");
          row.className = "markus-newsletter-list";
          var box = document.createElement("input");
          box.type = "checkbox";
          box.id = "newsletter-list-" + index;
          box.name = "l";
          box.value = entry.id;
          box.checked = entry.subscribed === true;
          var label = make("label", entry.description ? entry.name + ": " + entry.description : entry.name);
          label.htmlFor = box.id;
          row.appendChild(box);
          row.appendChild(document.createTextNode(" "));
          row.appendChild(label);
          holder.appendChild(row);
        });
        var confirm = one(root, "[data-newsletter-section=delete]");
        fillToken(form, token);
        one(confirm, "form").elements.t.value = token;
        show(one(confirm, "form"), true);
        one(confirm, "[data-newsletter-back]").href = root.getAttribute("data-preferences-href") + "?token=" + encodeURIComponent(token);
        show(step === "delete" ? confirm : manage, true);
        if (NOTICES[message] && step !== "delete") {
          var notice = one(root, "[data-newsletter-notice]");
          notice.textContent = NOTICES[message];
          show(notice, true);
        }
      }).catch(function () { expired(root); });
    }
  };

  function start() {
    var root = document.querySelector("[data-newsletter-page]");
    if (!root) return;
    var page = pages[root.getAttribute("data-newsletter-page")];
    if (page) page(root, new URLSearchParams(window.location.search));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
