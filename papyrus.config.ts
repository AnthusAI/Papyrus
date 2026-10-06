import { defineSite } from "./lib/define-site";
import { anthUsBrand } from "./publications/anth_us/brand";
import { pilobolUsBrand } from "./publications/pilobol_us/brand";
import { threatIntelligenceBrand } from "./publications/threat_intelligence/brand";

export default defineSite({
  brands: [threatIntelligenceBrand, pilobolUsBrand, anthUsBrand],
  defaultBrand: "papyrus",
});
