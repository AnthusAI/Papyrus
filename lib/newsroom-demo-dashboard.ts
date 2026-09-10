import type { CategorySteeringDashboard } from "./category-repository";
import { getNewsroomDemoProfile, type NewsroomDemoProfile } from "./newsroom-demo-profile";
import type { SiteBrandId } from "./site-brand";

const PILOBOLUS_CATEGORY_LABELS: Record<string, { displayName: string; subtitle: string; description: string }> = {
  "category.foundation-model-scaling": {
    displayName: "Strangler-Fig Control Loops",
    subtitle: "Host encirclement, canopy pressure, and takeover timing",
    description: "Field notes on how strangler-fig encirclement reshapes access paths and control timing in Pilobolus research.",
  },
  "category.agent-memory": {
    displayName: "Mycelial Signal Routing",
    subtitle: "Network timing, propagation failure, and recovery paths",
    description: "Accepted subcategory for signal routing, persistence, and coordination across fungal network observations.",
  },
  "category.benchmark-saturation": {
    displayName: "Canopy Competition Metrics",
    subtitle: "Light capture, host stress, and encirclement saturation signals",
    description: "Metrics for when a host canopy loses effective control under sustained strangler pressure.",
  },
  "category.symbolic-connectionist-history": {
    displayName: "Fungal Network Field Logs",
    subtitle: "Seasonal intake logs and annotated field observations",
    description: "Historical field logs and intake notes that anchor Pilobolus fungus-among-us coverage.",
  },
};

export function applyPilobolusDemoDashboardContent(
  dashboard: CategorySteeringDashboard,
  profile: NewsroomDemoProfile = getNewsroomDemoProfile("pilobol-us"),
): CategorySteeringDashboard {
  const localized = structuredClone(dashboard);
  localized.canonicalCorpusId = profile.corpusId;
  localized.canonicalCategorySetId = profile.categorySetId;

  for (const corpus of localized.corpora) {
    if (corpus.role === "canonical") {
      corpus.id = profile.corpusId;
      corpus.name = profile.canonicalCorpusName;
    }
    if (corpus.role === "source") {
      corpus.id = profile.sourceCorpusId;
      corpus.name = profile.sourceCorpusName;
    }
  }

  for (const run of localized.importRuns) {
    run.classifierId = profile.classifierId;
    if (run.corpusId.includes("demo-canonical")) run.corpusId = profile.corpusId;
    if (run.corpusId.includes("demo-source")) run.corpusId = profile.sourceCorpusId;
  }

  for (const set of localized.categorySets) {
    set.classifierId = profile.classifierId;
    if (set.id === "category-set-demo-canonical") {
      set.id = profile.categorySetId;
      set.lineageId = profile.categorySetId;
      set.corpusId = profile.corpusId;
      set.displayName = profile.categorySetLabel;
      set.description = "Accepted Pilobolus steering tree for fungus-among-us field coverage.";
    }
    if (set.id === "category-set-demo-source") {
      set.id = profile.sourceCategorySetId;
      set.lineageId = profile.sourceCategorySetId;
      set.corpusId = profile.sourceCorpusId;
      set.displayName = "Pilobolus Source Intake Tree";
      set.description = "Source intake categories for Pilobolus field material.";
    }
  }

  for (const tree of localized.categoryTrees) {
    tree.classifierId = profile.classifierId;
    tree.corpusId = profile.corpusId;
    tree.displayName = `${profile.brandLabel} Steering Tree`;
    tree.description = "Accepted topic tree for Pilobolus field-notes coverage.";
  }

  const relabelCategory = <T extends { categoryKey?: string | null; displayName?: string | null; subtitle?: string | null; description?: string | null }>(
    row: T,
  ): T => {
    const labels = row.categoryKey ? PILOBOLUS_CATEGORY_LABELS[row.categoryKey] : undefined;
    if (!labels) return row;
    return {
      ...row,
      displayName: labels.displayName,
      subtitle: labels.subtitle,
      description: labels.description,
    };
  };

  localized.categorys = localized.categorys.map(relabelCategory);
  localized.categoryNodes = localized.categoryNodes.map(relabelCategory);

  localized.categoryKeywords = localized.categoryKeywords.map((keyword) => {
    if (keyword.categoryKey === "category.foundation-model-scaling") {
      return { ...keyword, keyword: "strangler fig", normalizedKeyword: "strangler fig" };
    }
    if (keyword.categoryKey === "category.agent-memory") {
      return { ...keyword, keyword: "mycelial routing", normalizedKeyword: "mycelial routing" };
    }
    return keyword;
  });

  localized.proposals = localized.proposals.map((proposal) => {
    const relabeled = relabelCategory(proposal);
    if (proposal.proposalKind === "rename-category") {
      return {
        ...relabeled,
        title: "Rename strangler-fig control category",
        summary: "Field intake consistently uses strangler-fig encirclement language instead of generic scaling terminology.",
      };
    }
    if (proposal.proposalKind === "create-category") {
      return {
        ...relabeled,
        title: "Create mycelial routing subcategory",
        summary: "Discovery found a child topic under strangler-fig control loops for signal routing evidence.",
        displayName: "Mycelial Signal Routing",
        description: "Candidate subcategory covering routing, persistence, and propagation across fungal networks.",
      };
    }
    if (proposal.proposalKind === "relationship-proposal") {
      return {
        ...relabeled,
        title: "Link control loop category to canopy metrics entity",
        summary: "Evidence suggests strangler-fig control loops relate to canopy competition metrics.",
      };
    }
    return relabeled;
  });

  localized.references = localized.references.map((reference, index) => ({
    ...reference,
    corpusId: profile.sourceCorpusId,
    title: index === 0
      ? "Strangler Fig Host Encirclement Field Notes"
      : "Mycelial Coordination Under Canopy Stress",
    sourceUri: index === 0
      ? "s3://pilobol-us-demo/corpora/pilobol-us-source/strangler-fig-field-notes-001.md"
      : "s3://pilobol-us-demo/corpora/pilobol-us-source/mycelial-canopy-stress-002.md",
    storagePath: index === 0
      ? "corpora/pilobol-us-source/strangler-fig-field-notes-001.md"
      : "corpora/pilobol-us-source/mycelial-canopy-stress-002.md",
  }));

  localized.referenceAttachments = localized.referenceAttachments.map((attachment, index) => ({
    ...attachment,
    sourceUri: index % 2 === 0
      ? "s3://pilobol-us-demo/corpora/pilobol-us-source/strangler-fig-field-notes-001.md"
      : "s3://pilobol-us-demo/corpora/pilobol-us-source/mycelial-canopy-stress-002.md",
    storagePath: index % 2 === 0
      ? "corpora/pilobol-us-source/strangler-fig-field-notes-001.md"
      : "corpora/pilobol-us-source/mycelial-canopy-stress-002.md",
    filename: index % 2 === 0 ? "strangler-fig-field-notes-001.md" : "mycelial-canopy-stress-002.md",
  }));

  localized.semanticNodes = localized.semanticNodes.map((node, index) => ({
    ...node,
    corpusId: index === 0 ? profile.corpusId : profile.sourceCorpusId,
    displayName: index === 0 ? "Canopy Competition Metrics" : "Intake Rationale",
  }));

  localized.messages = localized.messages.map((message) => {
    if (message.messageKind === "ingestion_rationale") {
      return {
        ...message,
        body: "Imported as a useful holdout against generic platform demo intake.",
        summary: "Pilobolus intake rationale",
      };
    }
    if (message.messageKind === "reporting_context_packet") {
      const metadata = message.metadata && typeof message.metadata === "object" && !Array.isArray(message.metadata)
        ? message.metadata as Record<string, unknown>
        : {};
      const reporting = metadata.reporting && typeof metadata.reporting === "object" && !Array.isArray(metadata.reporting)
        ? metadata.reporting as Record<string, unknown>
        : {};
      return {
        ...message,
        body: "Context packet for a Pilobolus field-notes candidate. Editors can select, merge, brief, hold, or kill this packet without creating reader copy.",
        summary: "Reporting context packet: strangler-fig control-loop angle",
        metadata: {
          ...metadata,
          reporting: {
            ...reporting,
            sectionKey: "field-notes",
            recommendedAngle: "Focus on host encirclement timing and mycelial routing evidence.",
            copywriterBrief: "Use accepted Pilobolus field-note evidence before drafting.",
          },
        },
      };
    }
    return message;
  });

  localized.assignments = localized.assignments.map((assignment, index) => {
    if (assignment.assignmentTypeKey === "reporting.edition-candidate") {
      return {
        ...assignment,
        title: "Field-notes reporting candidate 1: Strangler-fig control-loop shift",
        summary: "Create reporting context for a Pilobolus field-notes candidate; do not create a draft Item until editor selection.",
        brief: "Report a section-ready candidate for Field Notes, option 1.",
        primaryFocusCategoryKey: "category.foundation-model-scaling",
        topicScopeCategoryKeys: ["category.foundation-model-scaling"],
      };
    }
    if (index === 0) {
      return {
        ...assignment,
        title: "Reference intake: strangler-fig field notes",
        summary: "Review and curate Pilobolus source intake for strangler-fig encirclement field notes.",
      };
    }
    return {
      ...assignment,
      title: "Reference intake: mycelial canopy stress log",
      summary: "Review Pilobolus source intake for mycelial coordination under canopy stress.",
    };
  });

  localized.doctrineRecords = localized.doctrineRecords.map((record) => {
    const editorial = record.editorial && typeof record.editorial === "object" && !Array.isArray(record.editorial)
      ? record.editorial as Record<string, unknown>
      : null;
    if (editorial?.kind === "mission") {
      return {
        ...record,
        title: "Pilobolus Editorial Mission",
        body: [
          "Pilobolus publishes field notes that help readers see fungus-among-us coordination, strangler-fig control loops, and mycelial signal routing with inspectable evidence.",
          "Coverage should stay source-disciplined, canopy-aware, and explicit about what remains uncertain in the field record.",
        ],
      };
    }
    if (editorial?.kind === "policy") {
      return {
        ...record,
        title: "Pilobolus Editorial Policy",
        body: [
          "Publication doctrine is the global inclusion standard for Pilobol.us; desk doctrine sets local intake priorities for field notes and source intake.",
          "Field-notes reporting should prioritize accepted Pilobolus references and annotated intake artifacts—not the Papyrus platform knowledge base.",
          "High-risk claims about host takeover or network control require explicit uncertainty handling and accepted source linkage.",
        ],
      };
    }
    return record;
  });

  localized.artifacts = localized.artifacts.map((artifact) => ({
    ...artifact,
    corpusId: profile.corpusId,
    artifactId: "s3://pilobol-us-demo/accepted-category-set.json",
    displayName: "Pilobolus Accepted Steering Tree JSON",
  }));

  localized.lexicalSteeringRules = localized.lexicalSteeringRules.map((rule) => ({
    ...rule,
    source: "pilobol-us-lexical-steering.yml",
    createdBy: "pilobol-us-config",
  }));

  return localized;
}

export function shouldUsePilobolusDemoDashboard(brandId: SiteBrandId): boolean {
  return brandId === "pilobol-us";
}
