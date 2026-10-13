/*
 * <papyrus-search>: client-side search over /_data/search-index.json.
 *
 * Framework-free and dependency-free. Include it once with
 *   <script src="/_plugins/papyrus-search@1.js" defer></script>
 * and place the element anywhere in a page:
 *   <papyrus-search></papyrus-search>
 *
 * Attributes (all optional)
 *   src          address of the index           default /_data/search-index.json
 *   placeholder  input placeholder              default "Search"
 *   label        accessible name of the input   default "Search this site"
 *   limit        most results shown             default 10
 *   min-length   shortest query that searches   default 2
 *
 * The element renders into its own light DOM, so the site's CSS styles it:
 * form.papyrus-search, input.papyrus-search-input, ul.papyrus-search-results,
 * p.papyrus-search-status. Without JavaScript the element is empty and the
 * page is unchanged. The index is fetched on first focus, not at page load.
 * Only same-site addresses (starting with "/") are ever linked.
 */
(function () {
  "use strict";

  var DEFAULT_SOURCE = "/_data/search-index.json";

  function normalize(text) {
    return String(text || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  }

  function words(text) {
    return normalize(text).split(/[^a-z0-9]+/).filter(Boolean);
  }

  function scoreEntry(entry, tokens, phrase) {
    var title = normalize(entry.title);
    var titleWords = words(entry.title);
    var summary = normalize(entry.summary);
    var tags = (entry.tags || []).map(normalize);
    var total = 0;
    for (var index = 0; index < tokens.length; index += 1) {
      var token = tokens[index];
      var tokenScore = 0;
      if (titleWords.indexOf(token) !== -1) tokenScore = Math.max(tokenScore, 6);
      if (titleWords.some(function (word) { return word.indexOf(token) === 0; })) tokenScore = Math.max(tokenScore, 5);
      if (title.indexOf(token) !== -1) tokenScore = Math.max(tokenScore, 3);
      if (tags.some(function (tag) { return tag === token || words(tag).indexOf(token) !== -1; })) tokenScore = Math.max(tokenScore, 4);
      if (tags.some(function (tag) { return tag.indexOf(token) !== -1; })) tokenScore = Math.max(tokenScore, 2);
      if (summary.indexOf(token) !== -1) tokenScore = Math.max(tokenScore, 1);
      if (tokenScore === 0) return 0;
      total += tokenScore;
    }
    if (tokens.length > 1 && title.indexOf(phrase) !== -1) total += 4;
    return total;
  }

  function rank(entries, query, limit) {
    var tokens = words(query);
    if (tokens.length === 0) return [];
    var phrase = tokens.join(" ");
    return (entries || [])
      .map(function (entry) { return { entry: entry, score: scoreEntry(entry, tokens, phrase) }; })
      .filter(function (scored) { return scored.score > 0; })
      .sort(function (left, right) {
        if (right.score !== left.score) return right.score - left.score;
        return String(right.entry.date || "").localeCompare(String(left.entry.date || ""));
      })
      .slice(0, limit)
      .map(function (scored) { return scored.entry; });
  }

  function isSiteAddress(address) {
    return typeof address === "string" && address.charAt(0) === "/" && address.charAt(1) !== "/";
  }

  var api = { rank: rank, words: words, normalize: normalize, isSiteAddress: isSiteAddress };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window === "undefined" || typeof HTMLElement === "undefined") return;
  window.PapyrusSearch = api;

  function integerAttribute(element, name, fallback) {
    var parsed = parseInt(element.getAttribute(name), 10);
    return isNaN(parsed) || parsed < 1 ? fallback : parsed;
  }

  function PapyrusSearchElement() {
    return Reflect.construct(HTMLElement, [], PapyrusSearchElement);
  }
  PapyrusSearchElement.prototype = Object.create(HTMLElement.prototype);
  PapyrusSearchElement.prototype.constructor = PapyrusSearchElement;

  PapyrusSearchElement.prototype.connectedCallback = function () {
    if (this._ready) return;
    this._ready = true;
    this._entries = null;
    this._loading = null;
    var form = document.createElement("form");
    form.className = "papyrus-search";
    form.setAttribute("role", "search");
    var input = document.createElement("input");
    input.type = "search";
    input.className = "papyrus-search-input";
    input.autocomplete = "off";
    input.setAttribute("aria-label", this.getAttribute("label") || "Search this site");
    input.placeholder = this.getAttribute("placeholder") || "Search";
    var status = document.createElement("p");
    status.className = "papyrus-search-status";
    status.setAttribute("role", "status");
    var results = document.createElement("ul");
    results.className = "papyrus-search-results";
    form.appendChild(input);
    form.appendChild(status);
    form.appendChild(results);
    this.appendChild(form);
    this._input = input;
    this._status = status;
    this._results = results;
    var element = this;
    form.addEventListener("submit", function (event) { event.preventDefault(); });
    input.addEventListener("focus", function () { element.load(); });
    input.addEventListener("input", function () { element.search(); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { input.value = ""; element.search(); }
      if (event.key === "ArrowDown") {
        var first = results.querySelector("a");
        if (first) { event.preventDefault(); first.focus(); }
      }
    });
  };

  PapyrusSearchElement.prototype.load = function () {
    if (this._entries) return Promise.resolve(this._entries);
    if (this._loading) return this._loading;
    var element = this;
    var source = this.getAttribute("src") || DEFAULT_SOURCE;
    this._loading = fetch(source, { credentials: "omit" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (entries) {
        element._entries = Array.isArray(entries) ? entries : [];
        return element._entries;
      })
      .catch(function () {
        element._loading = null;
        element._status.textContent = "Search is unavailable right now.";
        return [];
      });
    return this._loading;
  };

  PapyrusSearchElement.prototype.search = function () {
    var element = this;
    var query = this._input.value;
    var minimum = integerAttribute(this, "min-length", 2);
    if (query.trim().length < minimum) {
      this._results.textContent = "";
      this._status.textContent = "";
      return;
    }
    this.load().then(function (entries) {
      if (element._input.value !== query) return;
      var found = rank(entries, query, integerAttribute(element, "limit", 10));
      element._results.textContent = "";
      found.forEach(function (entry) {
        if (!isSiteAddress(entry.url)) return;
        var item = document.createElement("li");
        var link = document.createElement("a");
        link.href = entry.url;
        link.textContent = entry.title;
        item.appendChild(link);
        if (entry.summary) {
          var summary = document.createElement("span");
          summary.className = "papyrus-search-summary";
          summary.textContent = entry.summary;
          item.appendChild(summary);
        }
        element._results.appendChild(item);
      });
      element._status.textContent = found.length === 0 ? "No results." : found.length + (found.length === 1 ? " result." : " results.");
    });
  };

  if (!window.customElements.get("papyrus-search")) window.customElements.define("papyrus-search", PapyrusSearchElement);
})();
