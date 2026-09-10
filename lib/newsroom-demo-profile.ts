import { resolveSiteBrandId, type SiteBrandId } from "./site-brand";

export type NewsroomDemoProfile = {
  brandLabel: string;
  canonicalCorpusName: string;
  sourceCorpusName: string;
  categorySetLabel: string;
  classifierId: string;
  corpusId: string;
  sourceCorpusId: string;
  categorySetId: string;
  sourceCategorySetId: string;
};

const PAPYRUS_DEMO_PROFILE: NewsroomDemoProfile = {
  brandLabel: "Papyrus",
  canonicalCorpusName: "Canonical Demo Corpus",
  sourceCorpusName: "Source Demo Corpus",
  categorySetLabel: "Demo Canonical Category Set",
  classifierId: "demo-canonical-classifier",
  corpusId: "knowledge-corpus-demo-canonical",
  sourceCorpusId: "knowledge-corpus-demo-source",
  categorySetId: "category-set-demo-canonical",
  sourceCategorySetId: "category-set-demo-source",
};

const PILOBOLUS_DEMO_PROFILE: NewsroomDemoProfile = {
  brandLabel: "Pilobolus",
  canonicalCorpusName: "Pilobolus Field Notes Corpus",
  sourceCorpusName: "Pilobolus Source Intake",
  categorySetLabel: "Pilobolus Steering Tree",
  classifierId: "pilobolus-demo-classifier",
  corpusId: "knowledge-corpus-pilobolus-demo-canonical",
  sourceCorpusId: "knowledge-corpus-pilobolus-demo-source",
  categorySetId: "category-set-pilobolus-demo-canonical",
  sourceCategorySetId: "category-set-pilobolus-demo-source",
};

export function getNewsroomDemoProfile(brandId: SiteBrandId = resolveSiteBrandId()): NewsroomDemoProfile {
  if (brandId === "pilobol-us") return PILOBOLUS_DEMO_PROFILE;
  return PAPYRUS_DEMO_PROFILE;
}

export function isPilobolusDemoBrand(brandId: SiteBrandId = resolveSiteBrandId()): boolean {
  return brandId === "pilobol-us";
}
