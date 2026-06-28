function parsePresentationChoices(value) {
  return String(value ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function buildCapabilities(raw) {
  const presentationChoices = parsePresentationChoices(raw.presentationChoices);
  const forcedPresentation = raw.forcedPresentation || null;
  return {
    siteBrand: raw.siteBrand ?? "papyrus",
    defaultPresentation: raw.defaultPresentation ?? "newspaper",
    forcedPresentation,
    presentationChoices,
    allowsPresentationChoice: presentationChoices.length > 1,
    supportsNewspaper: presentationChoices.includes("newspaper"),
    supportsBlog: presentationChoices.includes("blog"),
    supportsMagazine: presentationChoices.includes("magazine"),
  };
}

function readCapabilitiesFromDocument() {
  const root = document.documentElement;
  return {
    siteBrand: root.dataset.siteBrand ?? "papyrus",
    defaultPresentation: root.dataset.defaultPresentation ?? "newspaper",
    forcedPresentation: root.dataset.forcedPresentation ?? null,
    presentationChoices: root.dataset.presentationChoices ?? "",
  };
}

function capabilityLabel(capability) {
  if (capability === "presentation-choice") return "presentation format choice";
  return capability;
}

function assertCapability(world, capability) {
  const capabilities = world.capabilities;
  if (!capabilities) {
    throw new Error("Site capabilities were not probed before this step ran.");
  }

  if (capability === "presentation-choice" && !capabilities.allowsPresentationChoice) {
    return `Site brand "${capabilities.siteBrand}" does not allow presentation format choice`;
  }
  if (capability === "newspaper" && !capabilities.supportsNewspaper) {
    return `Site brand "${capabilities.siteBrand}" does not support the newspaper presentation`;
  }
  if (capability === "blog" && !capabilities.supportsBlog) {
    return `Site brand "${capabilities.siteBrand}" does not support the blog presentation`;
  }
  if (capability === "magazine" && !capabilities.supportsMagazine) {
    return `Site brand "${capabilities.siteBrand}" does not support the magazine presentation`;
  }
  return null;
}

function requireCapability(world, capability) {
  const reason = assertCapability(world, capability);
  if (reason) {
    throw new Error(`SKIP: ${reason}`);
  }
}

function getEffectivePresentation(world) {
  const capabilities = world.capabilities;
  if (!capabilities) return "newspaper";
  return capabilities.forcedPresentation ?? capabilities.defaultPresentation;
}

function scenarioRequiresCapability(tags, capability) {
  const normalized = capability === "presentation-choice" ? "presentation-choice" : capability;
  return tags.some((tag) => tag.name === `@${normalized}` || tag.name === normalized);
}

function shouldSkipScenario(world, tags = []) {
  if (scenarioRequiresCapability(tags, "brand-agnostic")) {
    return null;
  }

  const checks = ["newspaper", "blog", "magazine", "presentation-choice"];
  for (const capability of checks) {
    if (!scenarioRequiresCapability(tags, capability)) continue;
    const reason = assertCapability(world, capability);
    if (reason) return reason;
  }
  return null;
}

module.exports = {
  buildCapabilities,
  capabilityLabel,
  getEffectivePresentation,
  readCapabilitiesFromDocument,
  requireCapability,
  shouldSkipScenario,
};
