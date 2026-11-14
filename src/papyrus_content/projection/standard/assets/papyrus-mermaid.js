// Renders ```mermaid blocks as diagrams. Loaded only on pages that contain one. The library is the site's own copy
// (data-library), fetched only now; nothing comes from a third party. Without this script, or if rendering fails, the
// diagram source stays in its <pre>, readable as text.
(function () {
  var loader = document.currentScript;
  var library = loader && loader.getAttribute("data-library");
  var found = Array.prototype.slice.call(document.querySelectorAll("pre > code.language-mermaid"));
  if (!library || !found.length) return;

  var diagrams = found.map(function (code) {
    return { pre: code.parentNode, source: code.textContent, figure: null, canvas: null };
  });
  var counter = 0;

  var style = document.createElement("style");
  style.textContent =
    ".papyrus-diagram{margin:1.5rem 0}" +
    ".papyrus-diagram-canvas{overflow-x:auto;text-align:center}" +
    ".papyrus-diagram-canvas svg{max-width:100%;height:auto}" +
    ".papyrus-diagram-source summary{cursor:pointer;font-size:.875em}" +
    ".papyrus-diagram-note{font-size:.875em}";
  document.head.appendChild(style);

  function color(token, fallback) {
    var probe = document.createElement("span");
    probe.style.color = fallback;
    var value = getComputedStyle(document.body).getPropertyValue(token).trim();
    if (value) probe.style.color = value;
    document.body.appendChild(probe);
    var resolved = getComputedStyle(probe).color;
    document.body.removeChild(probe);
    return resolved;
  }

  // The diagram follows the site's own tokens (and so its light and dark themes). It is drawn in the text colour on the
  // background colour with no colour coding: meaning is carried by shape, line style and labels, never by colour alone.
  function theme() {
    var body = getComputedStyle(document.body);
    var ink = color("--papyrus-ink", body.color);
    var background = color("--papyrus-bg", body.backgroundColor === "rgba(0, 0, 0, 0)" ? "white" : body.backgroundColor);
    var panel = color("--papyrus-band-bg", background);
    return {
      background: background,
      primaryColor: panel,
      primaryTextColor: ink,
      primaryBorderColor: ink,
      secondaryColor: panel,
      secondaryTextColor: ink,
      secondaryBorderColor: ink,
      tertiaryColor: background,
      tertiaryTextColor: ink,
      tertiaryBorderColor: ink,
      lineColor: ink,
      textColor: ink,
      noteBkgColor: panel,
      noteTextColor: ink,
      noteBorderColor: ink,
      edgeLabelBackground: background,
      fontFamily: body.fontFamily
    };
  }

  function kind(source) {
    var lines = source.split("\n");
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line || line.indexOf("%%") === 0 || line === "---") continue;
      var word = line.split(/[\s;]/)[0].replace(/-v2$/, "");
      return word.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
    }
    return "";
  }

  function describe(svg, source) {
    var type = kind(source);
    var label = type ? "Diagram (" + type + "). The source follows the diagram." : "Diagram. The source follows the diagram.";
    var title = svg.querySelector("title");
    if (title && title.textContent.trim()) label = title.textContent.trim() + ". " + label;
    else {
      var added = document.createElementNS("http://www.w3.org/2000/svg", "title");
      added.textContent = label;
      svg.insertBefore(added, svg.firstChild);
    }
    return label;
  }

  function fail(diagram, id) {
    var leftover = document.getElementById("d" + id);
    if (leftover && leftover.parentNode) leftover.parentNode.removeChild(leftover);
    if (diagram.figure) {
      diagram.figure.parentNode.replaceChild(diagram.pre, diagram.figure);
      diagram.figure = diagram.canvas = null;
    }
    var next = diagram.pre.nextSibling;
    if (!next || !next.classList || !next.classList.contains("papyrus-diagram-note")) {
      var note = document.createElement("p");
      note.className = "papyrus-diagram-note";
      note.setAttribute("role", "status");
      note.textContent = "This diagram could not be drawn; its source is shown instead.";
      diagram.pre.parentNode.insertBefore(note, diagram.pre.nextSibling);
    }
  }

  function draw(mermaid, diagram) {
    counter += 1;
    var id = "papyrus-mermaid-" + counter;
    return mermaid.render(id, diagram.source).then(function (result) {
      if (!diagram.figure) {
        var figure = document.createElement("figure");
        figure.className = "papyrus-diagram";
        var canvas = document.createElement("div");
        canvas.className = "papyrus-diagram-canvas";
        canvas.setAttribute("role", "img");
        var details = document.createElement("details");
        details.className = "papyrus-diagram-source";
        var summary = document.createElement("summary");
        summary.textContent = "Diagram source";
        diagram.pre.parentNode.insertBefore(figure, diagram.pre);
        details.appendChild(summary);
        details.appendChild(diagram.pre);   // the original <pre> moves in: it is the text alternative
        figure.appendChild(canvas);
        figure.appendChild(details);
        diagram.figure = figure;
        diagram.canvas = canvas;
      }
      diagram.canvas.innerHTML = result.svg;   // strict security level: Mermaid sanitises the markup it returns
      var svg = diagram.canvas.querySelector("svg");
      if (svg) diagram.canvas.setAttribute("aria-label", describe(svg, diagram.source));
    }).catch(function () { fail(diagram, id); });
  }

  function run(mermaid) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      htmlLabels: false,
      theme: "base",
      themeVariables: theme(),
      flowchart: { htmlLabels: false }
    });
    // One at a time: Mermaid renders through shared state.
    return diagrams.reduce(function (done, diagram) {
      return done.then(function () { return draw(mermaid, diagram); });
    }, Promise.resolve());
  }

  var element = document.createElement("script");
  element.src = library;
  element.async = true;
  element.onload = function () {
    var holder = window.mermaid || (window.__esbuild_esm_mermaid_nm && window.__esbuild_esm_mermaid_nm.mermaid);
    var mermaid = holder && (holder.default || holder);
    if (!mermaid || typeof mermaid.render !== "function") return;
    run(mermaid);
    var again = function () { run(mermaid); };   // a theme change redraws in the new colours
    if (window.matchMedia) {
      var query = window.matchMedia("(prefers-color-scheme: dark)");
      if (query.addEventListener) query.addEventListener("change", again);
    }
    if (window.MutationObserver) new MutationObserver(again).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  };
  document.head.appendChild(element);
})();
