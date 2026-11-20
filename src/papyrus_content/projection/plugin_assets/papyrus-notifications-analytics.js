/*
 * Google Analytics 4 events for the notifications plugin's subscribe and manage pages (PPY-5a1607).
 *
 * Loaded by those pages only, and only on a site that sets a GA4 measurement id. It sends events through the site's own `gtag`, which the
 * page's Consent Mode already gates: a reader who declined analytics sends only the cookieless pings Consent Mode allows, and this script
 * stores nothing (no cookie, no localStorage, no sessionStorage) and sets no client id or user id. The events are sent from the page, never
 * from the server. No inline script: it works under a strict CSP.
 *
 * The pages scripts call `window.papyrusNotificationsAnalytics.track(name, params)` (and `trackLoad` for an event that belongs to arriving
 * on a page). Only the events below are sent, with only the parameters listed, and nothing else can be set:
 *
 *   subscribe_start      the subscribe form was focused or submitted (once per form)
 *   subscribe_submitted  the service accepted a subscribe request
 *   subscribe_confirmed  the confirmed page was opened
 *   preferences_changed  the manage page opened after a save
 *   unsubscribe          the unsubscribed page was opened (or the manage page after "unsubscribe from everything")
 *   subscribe_error      a subscribe request failed, or the service could not be reached
 *
 *   kind       the id of the list the event is about, several joined by commas; `all` when every list is meant
 *   form       the signup placement (the component's `form-id`)
 *   page_type  subscribe, confirm, confirmed, preferences, unsubscribe, unsubscribed, expired or other
 *
 * Every event carries `page_location` set to the address without its query string and fragment (confirm and manage links carry tokens),
 * and a value that looks like an address, a token or a subject is dropped. `trackLoad` sends nothing when the page was reloaded or reached
 * with the back button, so reloading a confirmed page does not count a second time. When analytics is blocked or `gtag` is missing,
 * nothing is sent and the page works as before.
 */
(function () {
  "use strict";

  var EVENTS = { subscribe_start: 1, subscribe_submitted: 1, subscribe_confirmed: 1, preferences_changed: 1, unsubscribe: 1, subscribe_error: 1 };
  var PAGE_TYPES = { subscribe: 1, confirm: 1, confirmed: 1, preferences: 1, unsubscribe: 1, unsubscribed: 1, expired: 1, other: 1 };
  var LIST_ID = /^[a-z][a-z0-9-]{0,39}$/;
  var FORM_ID = /^[a-z0-9_-]{1,40}$/;
  var IDENTITY_VALUE = /^ss1_|@|^[A-Za-z0-9._~-]{32,}$/;

  function kind(value) {
    var ids = String(value == null ? "" : value).split(",").map(function (id) { return id.trim(); });
    var ok = ids.length > 0 && ids.every(function (id) { return LIST_ID.test(id) || id === "all"; });
    var text = ids.join(",");
    return ok && text.length <= 100 && !IDENTITY_VALUE.test(text) ? text : "";
  }

  function clean(params) {
    var out = {};
    var source = params || {};
    var list = kind(source.kind);
    if (list) out.kind = list;
    var form = String(source.form == null ? "" : source.form);
    if (FORM_ID.test(form) && !IDENTITY_VALUE.test(form)) out.form = form;
    var page = String(source.page_type == null ? "" : source.page_type);
    if (PAGE_TYPES.hasOwnProperty(page)) out.page_type = page;
    return out;
  }

  function track(name, params) {
    if (!EVENTS.hasOwnProperty(name) || typeof window.gtag !== "function") return false;
    var data = clean(params);
    try {
      data.page_location = window.location.origin + window.location.pathname;
      window.gtag("event", name, data);
      return true;
    } catch (e) {
      return false;
    }
  }

  // The navigation entry says how this page was reached. Without it (an old browser) the page counts as freshly opened.
  function fresh() {
    try {
      var entries = window.performance && window.performance.getEntriesByType ? window.performance.getEntriesByType("navigation") : [];
      var type = entries && entries[0] ? entries[0].type : "navigate";
      return type !== "reload" && type !== "back_forward";
    } catch (e) {
      return true;
    }
  }

  function trackLoad(name, params) {
    return fresh() ? track(name, params) : false;
  }

  window.papyrusNotificationsAnalytics = { track: track, trackLoad: trackLoad };
})();
