/* Reference lists that load more as the reader scrolls (::include{kind="references" paged="true"}).
   The first page is in the HTML and a plain link ("Load more", rel=next) leads to the next static page, so nothing here is needed to read the list.
   With a script the link becomes a button that appends the next data file's cards in place. Where IntersectionObserver exists the next file is also
   fetched as the reader nears the end, a few files at a time; then the button asks, so the footer stays reachable. The cards are HTML drawn by the build
   (including the site's own card drawing), so this file draws nothing: it inserts. */
(function () {
  var AUTO_PAGES = 5;
  var MARGIN = "600px 0px";

  function words(count) { return count === 1 ? "1 more Reference" : count + " more References"; }

  function setup(section) {
    var grid = section.querySelector("[data-reference-grid]");
    var more = section.querySelector("[data-reference-more]");
    var status = section.querySelector("[data-reference-status]");
    var link = more && more.querySelector("a");
    var next = more && more.getAttribute("data-src");
    if (!grid || !more || !status || !link || !next || !window.fetch) return;

    var button = document.createElement("button");
    button.type = "button";
    button.className = link.className;
    button.innerHTML = link.innerHTML;
    var label = button.querySelector("span") || button;
    var idleText = label.textContent;
    link.parentNode.replaceChild(button, link);

    var sentinel = document.createElement("div");
    sentinel.className = "home-page-sentinel";
    sentinel.setAttribute("aria-hidden", "true");
    more.parentNode.insertBefore(sentinel, more);

    var loading = false;
    var automatic = 0;
    var observer = null;

    function seen() {
      var keys = {};
      Array.prototype.forEach.call(grid.children, function (item) { keys[item.getAttribute("data-key")] = true; });
      return keys;
    }

    function stopWatching() {
      if (observer) { observer.disconnect(); observer = null; }
    }

    function watch() {
      stopWatching();
      if (!("IntersectionObserver" in window) || !next) return;
      observer = new IntersectionObserver(function (entries) {
        if (!entries.some(function (entry) { return entry.isIntersecting; })) return;
        if (automatic >= AUTO_PAGES) {
          stopWatching();
          status.textContent = "Press Load more to see more.";
          return;
        }
        automatic += 1;
        load(false);
      }, { rootMargin: MARGIN });
      observer.observe(sentinel);
    }

    function busy(isBusy, text) {
      loading = isBusy;
      button.setAttribute("aria-disabled", isBusy ? "true" : "false");
      if (isBusy) section.setAttribute("aria-busy", "true"); else section.removeAttribute("aria-busy");
      label.textContent = text;
    }

    function finish(added, byKeyboard) {
      var hadFocus = document.activeElement === button;
      var shown = grid.children.length;
      if (!next) {
        stopWatching();
        more.hidden = true;
        sentinel.remove();
        status.textContent = (added ? "Loaded " + words(added) + ". " : "") + "All " + shown + " are shown.";
      } else {
        busy(false, idleText);
        status.textContent = added ? "Loaded " + words(added) + ". Showing " + shown + "." : "Nothing new in that page. Showing " + shown + ".";
        if (observer) { observer.unobserve(sentinel); observer.observe(sentinel); }   // look again: a short page may leave the end in view
      }
      if (byKeyboard) {   // a keyboard reader pressed the button: carry focus to the first new card, so Tab goes on through the new ones
        var first = grid.querySelector("[data-reference-new] a") || (hadFocus && grid.querySelector("li:last-child a"));
        if (first) first.focus();
      }
    }

    function load(byKeyboard) {
      if (loading || !next) return;
      busy(true, "Loading…");
      status.textContent = "Loading more References.";
      fetch(next, { credentials: "omit", headers: { Accept: "application/json" } })
        .then(function (response) {
          if (!response.ok) throw new Error("status " + response.status);
          return response.json();
        })
        .then(function (data) {
          var template = document.createElement("template");
          template.innerHTML = data.html || "";
          var have = seen();
          var added = 0;
          Array.prototype.forEach.call(grid.querySelectorAll("[data-reference-new]"), function (item) { item.removeAttribute("data-reference-new"); });
          Array.prototype.slice.call(template.content.children).forEach(function (item) {
            var key = item.getAttribute("data-key");
            if (key && have[key]) return;
            if (key) have[key] = true;
            if (added === 0) item.setAttribute("data-reference-new", "");
            grid.appendChild(item);
            added += 1;
          });
          next = data.next || null;
          finish(added, byKeyboard);
        })
        .catch(function () {
          stopWatching();
          busy(false, "Try again");
          status.textContent = "Could not load more References. Press the button to try again, or reload the page.";
        });
    }

    button.addEventListener("click", function (event) {
      if (loading) return;
      automatic = 0;
      var byKeyboard = event.detail === 0;
      load(byKeyboard);
      if (!observer && next) watch();
    });

    watch();
  }

  function start() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-paged="true"]'), setup);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
