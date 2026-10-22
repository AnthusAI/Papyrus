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

  function buildMenu(group) {
    var list = group.querySelector(".markus-actions-links");
    if (!list) return;
    var links = Array.prototype.slice.call(list.querySelectorAll("a"));
    var id = "actions-menu-" + Math.random().toString(36).slice(2, 8);
    var wrapper = document.createElement("div");
    wrapper.className = "markus-actions-menu";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "markus-actions-menu-button";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", id);
    button.setAttribute("aria-label", "More page actions");
    button.textContent = "More";
    var menu = document.createElement("ul");
    menu.id = id;
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", "More page actions");
    menu.hidden = true;
    links.forEach(function (link) {
      var item = document.createElement("li");
      item.setAttribute("role", "none");
      link.setAttribute("role", "menuitem");
      link.setAttribute("tabindex", "-1");
      item.appendChild(link);
      menu.appendChild(item);
    });
    wrapper.appendChild(button);
    wrapper.appendChild(menu);
    list.replaceWith(wrapper);

    function items() { return Array.prototype.slice.call(menu.querySelectorAll("[role=menuitem]")); }
    function open(focusIndex) {
      menu.hidden = false;
      button.setAttribute("aria-expanded", "true");
      var all = items();
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
      var all = items();
      var index = all.indexOf(document.activeElement);
      if (event.key === "ArrowDown") { event.preventDefault(); all[(index + 1) % all.length].focus(); }
      else if (event.key === "ArrowUp") { event.preventDefault(); all[(index - 1 + all.length) % all.length].focus(); }
      else if (event.key === "Home") { event.preventDefault(); all[0].focus(); }
      else if (event.key === "End") { event.preventDefault(); all[all.length - 1].focus(); }
      else if (event.key === "Escape") { event.preventDefault(); close(true); }
      else if (event.key === "Tab") { close(false); }
    });
    menu.addEventListener("click", function (event) {
      var link = event.target.closest("a");
      if (link) report(link.dataset.action);
      close(false);
    });
    document.addEventListener("click", function (event) { if (!wrapper.contains(event.target)) close(false); });
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
    buildMenu(group);
  });
})();
