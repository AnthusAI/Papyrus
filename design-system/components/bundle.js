/* @ds-bundle: {"format":4,"namespace":"Papyrus","components":[{"name":"Button"},{"name":"Eyebrow"},{"name":"Panel"},{"name":"Rule"}]} */
(function (global) {
  "use strict";

  var React = global.React;
  var h = React.createElement;

  function cx() {
    var out = [];
    for (var i = 0; i < arguments.length; i += 1) {
      if (arguments[i]) out.push(arguments[i]);
    }
    return out.join(" ");
  }

  function Button(props) {
    var p = props || {};
    var variant = p.variant || "default";
    var size = p.size || "default";
    var rest = {};
    for (var key in p) {
      if (key !== "variant" && key !== "size" && key !== "className" && key !== "children") {
        rest[key] = p[key];
      }
    }
    rest.type = p.type || "button";
    rest.className = cx(
      "ppy-btn",
      "ppy-btn--" + variant,
      size !== "default" ? "ppy-btn--" + size : null,
      p.className
    );
    return h("button", rest, p.children);
  }

  function Eyebrow(props) {
    var p = props || {};
    var tag = p.as || "span";
    var role = p.role || "kicker";
    var rest = {};
    for (var key in p) {
      if (key !== "as" && key !== "role" && key !== "tone" && key !== "className" && key !== "children") {
        rest[key] = p[key];
      }
    }
    rest.className = cx(
      "ppy-eyebrow",
      role !== "kicker" ? "ppy-eyebrow--" + role : null,
      p.tone === "alarm" ? "ppy-eyebrow--alarm" : null,
      p.className
    );
    return h(tag, rest, p.children);
  }

  function Panel(props) {
    var p = props || {};
    var tag = p.as || "section";
    var register = p.register || "chrome";
    var pad = p.pad || "default";
    var rest = {};
    for (var key in p) {
      if (
        key !== "as" && key !== "register" && key !== "pad" &&
        key !== "title" && key !== "className" && key !== "children"
      ) {
        rest[key] = p[key];
      }
    }
    rest.className = cx(
      "ppy-panel",
      "ppy-panel--" + register,
      pad !== "default" ? "ppy-panel--pad-" + pad : null,
      p.className
    );
    var kids = [];
    if (p.title) {
      kids.push(h("h2", { className: "ppy-panel__title", key: "title" }, p.title));
    }
    kids.push(h("div", { key: "body" }, p.children));
    return h(tag, rest, kids);
  }

  function Rule(props) {
    var p = props || {};
    var orientation = p.orientation || "horizontal";
    var weight = p.weight || "hairline";
    var rest = {};
    for (var key in p) {
      if (
        key !== "orientation" && key !== "weight" && key !== "soft" &&
        key !== "label" && key !== "className"
      ) {
        rest[key] = p[key];
      }
    }
    rest.className = cx(
      "ppy-rule",
      "ppy-rule--" + orientation,
      weight === "section" ? "ppy-rule--section" : null,
      p.soft ? "ppy-rule--soft" : null,
      p.className
    );
    rest.role = "separator";
    rest["aria-orientation"] = orientation;
    var line = h("hr", rest);
    if (!p.label) return line;
    return h("div", { className: "ppy-rule-label" }, [
      h(Eyebrow, { role: "section", key: "label" }, p.label),
      h("hr", Object.assign({}, rest, { key: "line" }))
    ]);
  }

  global.Papyrus = {
    Button: Button,
    Eyebrow: Eyebrow,
    Panel: Panel,
    Rule: Rule
  };
})(window);
