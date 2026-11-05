(function () {
  var groups = document.querySelectorAll("[data-papyrus-page-actions]");
  if (!groups.length) return;

  function report(action) {
    try { if (typeof window.gtag === "function") window.gtag("event", "page_action", { action: action }); } catch (e) {}
  }

  function textFor(group) {
    var title = group.dataset.title || document.title;
    var canonical = group.dataset.canonical || location.href;
    return fetch(group.dataset.markdown, { headers: { Accept: "text/markdown" }, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("markdown unavailable");
        return response.text();
      })
      .then(function (markdown) {
        // The twin already opens with the title and carries the canonical URL; add what is missing.
        var prefix = "";
        if (markdown.indexOf(canonical) === -1) prefix = canonical + "\n\n";
        // The server twin always carries its H1. A page written as page blocks has it after a summary line and the
        // ::band lines, so look for it anywhere rather than only at the top: the copy is the twin, never a rewrite of it.
        if (!/^# /m.test(markdown)) prefix = "# " + title + "\n\n" + prefix;
        return prefix + markdown;
      });
  }

  function fallbackCopy(group, text, status) {
    var area = document.createElement("textarea");
    area.className = "markus-actions-fallback";
    area.value = text;
    area.readOnly = true;
    area.setAttribute("aria-label", "Markdown to copy");
    group.appendChild(area);
    area.focus();
    area.select();
    var done = false;
    try { done = document.execCommand("copy"); } catch (e) {}
    status.textContent = done ? "Copied" : "Press Ctrl+C or Cmd+C to copy";
    if (done) area.remove();
  }

  function copy(group, status) {
    var wrote;
    if (navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
      // Handing the clipboard a promise keeps the write inside the user gesture, which Safari requires.
      var promise = textFor(group).then(function (text) { return new Blob([text], { type: "text/plain" }); });
      wrote = navigator.clipboard.write([new ClipboardItem({ "text/plain": promise })]);
    } else if (navigator.clipboard && navigator.clipboard.writeText) {
      wrote = textFor(group).then(function (text) { return navigator.clipboard.writeText(text); });
    } else {
      wrote = Promise.reject(new Error("no clipboard"));
    }
    return wrote.then(
      function () { status.textContent = "Copied"; },
      function () {
        return textFor(group).then(
          function (text) { fallbackCopy(group, text, status); },
          function () { status.textContent = "Could not copy. Use View as Markdown."; }
        );
      }
    ).then(function () { window.setTimeout(function () { if (!group.querySelector(".markus-actions-fallback")) status.textContent = ""; }, 4000); });
  }

  var ELLIPSIS = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" data-icon="ellipsis"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>';
  var SHARE = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" data-icon="share"><path d="M12 2v13"/><path d="m16 6-4-4-4 4"/><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/></svg>';

  // A menu button following the ARIA menu button pattern. `items` are elements that become menu items;
  // `options.choose` runs when one is chosen; `options.icon` is an SVG string for the button (else `options.text`).
  function menuFor(items, options) {
    var id = "actions-menu-" + Math.random().toString(36).slice(2, 8);
    var wrapper = document.createElement("div");
    wrapper.className = "markus-actions-menu";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "markus-actions-menu-button";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", id);
    button.setAttribute("aria-label", options.label);
    if (options.icon) {
      button.innerHTML = options.icon;
      button.title = options.label;
    } else {
      button.textContent = options.text;
    }
    var menu = document.createElement("ul");
    menu.id = id;
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", options.label);
    menu.hidden = true;
    items.forEach(function (element) {
      var item = document.createElement("li");
      item.setAttribute("role", "none");
      element.setAttribute("role", "menuitem");
      element.setAttribute("tabindex", "-1");
      item.appendChild(element);
      menu.appendChild(item);
    });
    wrapper.appendChild(button);
    wrapper.appendChild(menu);

    function entries() { return Array.prototype.slice.call(menu.querySelectorAll("[role=menuitem]")); }
    function open(focusIndex) {
      menu.hidden = false;
      button.setAttribute("aria-expanded", "true");
      var all = entries();
      if (focusIndex !== null) all[focusIndex < 0 ? all.length - 1 : focusIndex].focus();
    }
    function close(returnFocus) {
      menu.hidden = true;
      button.setAttribute("aria-expanded", "false");
      if (returnFocus) button.focus();
    }
    button.addEventListener("click", function () { if (menu.hidden) open(0); else close(false); });
    button.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") { event.preventDefault(); open(0); }
      else if (event.key === "ArrowUp") { event.preventDefault(); open(-1); }
    });
    menu.addEventListener("keydown", function (event) {
      var all = entries();
      var index = all.indexOf(document.activeElement);
      if (event.key === "ArrowDown") { event.preventDefault(); all[(index + 1) % all.length].focus(); }
      else if (event.key === "ArrowUp") { event.preventDefault(); all[(index - 1 + all.length) % all.length].focus(); }
      else if (event.key === "Home") { event.preventDefault(); all[0].focus(); }
      else if (event.key === "End") { event.preventDefault(); all[all.length - 1].focus(); }
      else if (event.key === "Escape") { event.preventDefault(); close(true); }
      else if (event.key === "Tab") { close(false); }
    });
    menu.addEventListener("click", function (event) {
      var chosen = event.target.closest("[role=menuitem]");
      if (chosen) options.choose(chosen);
      close(false);
    });
    document.addEventListener("click", function (event) { if (!wrapper.contains(event.target)) close(false); });
    return wrapper;
  }

  function buildMenu(group) {
    var list = group.querySelector(".markus-actions-links");
    if (!list) return;
    var links = Array.prototype.slice.call(list.querySelectorAll("a"));
    var icons = group.classList.contains("markus-page-actions-icons");
    list.replaceWith(menuFor(links, {
      label: "More page actions",
      text: "More",
      icon: icons ? ELLIPSIS : null,
      choose: function (link) { report(link.dataset.action); }
    }));
  }

  // Share the page or its Markdown twin: the device's share sheet when there is one, otherwise the address on the
  // clipboard. Only the title and the address are handed over, never the body.
  function share(group, status, kind) {
    var canonical = group.dataset.canonical || location.href;
    var address = kind === "markdown" ? new URL(group.dataset.markdown, canonical).href : canonical;
    report("share_" + kind);
    if (navigator.share) {
      navigator.share({ title: group.dataset.title || document.title, url: address }).then(function () {}, function () {});
      return;
    }
    var copied = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(address) : Promise.reject(new Error("no clipboard"));
    copied.then(
      function () { status.textContent = "Link copied"; },
      function () { status.textContent = address; }
    ).then(function () { window.setTimeout(function () { status.textContent = ""; }, 4000); });
  }

  function buildShare(group, status) {
    if (!group.hasAttribute("data-share")) return;
    var items = [["page", "Share the web page"], ["markdown", "Share the Markdown"]].map(function (pair) {
      var button = document.createElement("button");
      button.type = "button";
      button.dataset.share = pair[0];
      button.textContent = pair[1];
      return button;
    });
    group.insertBefore(menuFor(items, {
      label: "Share",
      icon: SHARE,
      choose: function (button) { share(group, status, button.dataset.share); }
    }), status);
  }

  groups.forEach(function (group) {
    group.classList.add("markus-actions-js");
    var status = group.querySelector(".markus-actions-status");
    var button = group.querySelector(".markus-copy-md");
    if (button) {
      button.addEventListener("click", function () {
        report("copy");
        status.textContent = "Copying";
        copy(group, status);
      });
    }
    Array.prototype.forEach.call(group.querySelectorAll(".markus-actions-icons a"), function (link) {
      link.addEventListener("click", function () { report(link.dataset.action); });
    });
    buildMenu(group);
    buildShare(group, status);
  });
})();
