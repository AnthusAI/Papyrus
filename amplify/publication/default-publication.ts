import { EDGE_DISTRIBUTION_ARN_ENVIRONMENT_VARIABLE, environmentOrConfigured, type IdentifierEnvironment } from "../deploy-identifiers";
import type { PapyrusPublicationConfig, PapyrusSiteBackendConfig } from "../site-backend-config";

export const DEFAULT_MARKUS_PUBLICATION: PapyrusPublicationConfig = { kind: "s3-projection", reprojectOnDeploy: true };

/**
 * The publication a site backend is built with. A Markus site that names a `reader` Amplify app
 * keeps publishing through it (`amplify-static`); every other Markus site gets the s3-projection
 * default unless it writes `publication: false`. Sites with another renderer get nothing unless
 * they write a `publication`.
 */
export function resolveSitePublication(
  backend: Pick<PapyrusSiteBackendConfig, "publication" | "reader">,
  rendererKind: string | undefined,
  environment: IdentifierEnvironment = process.env,
): PapyrusPublicationConfig | undefined {
  const publication = resolveConfiguredPublication(backend, rendererKind);
  if (publication === undefined) return undefined;
  // PAPYRUS_EDGE_DISTRIBUTION_ARN (set on the Amplify branch) wins over a written edgeDistributionArn, so the ARN need not be in Git.
  const edgeDistributionArn = environmentOrConfigured(EDGE_DISTRIBUTION_ARN_ENVIRONMENT_VARIABLE, publication.edgeDistributionArn, environment);
  return edgeDistributionArn === publication.edgeDistributionArn ? publication : { ...publication, edgeDistributionArn };
}

function resolveConfiguredPublication(
  backend: Pick<PapyrusSiteBackendConfig, "publication" | "reader">,
  rendererKind: string | undefined,
): PapyrusPublicationConfig | undefined {
  if (backend.publication === false) return undefined;
  if (backend.publication !== undefined) return backend.publication;
  if (rendererKind !== "markus") return undefined;
  if (backend.reader !== undefined) return undefined;
  return DEFAULT_MARKUS_PUBLICATION;
}
