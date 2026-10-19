import { generateEditionDateStaticParams, generateEditionItemStaticParams } from "../lib/reader-static-params";
import { getEditionDatePath } from "../lib/edition-routes";
import { editionsEnabled } from "../lib/site-brand";

const throwingRepository = {
  listPublishedEditions: async () => {
    throw new Error("must not list editions when editions are off");
  },
  loadEditionContent: async () => {
    throw new Error("must not load editions when editions are off");
  },
};

async function main() {
  const probe = process.argv[2];
  if (probe === "enumeration") {
    process.stdout.write(
      JSON.stringify({
        editionsEnabled: editionsEnabled(),
        dateParams: await generateEditionDateStaticParams(throwingRepository),
        itemParams: await generateEditionItemStaticParams(throwingRepository),
      }),
    );
    return;
  }
  if (probe === "setting") {
    process.stdout.write(JSON.stringify({ editionsEnabled: editionsEnabled(JSON.parse(process.argv[3])) }));
    return;
  }
  if (probe === "path") {
    process.stdout.write(JSON.stringify({ path: getEditionDatePath(process.argv[3], "") }));
    return;
  }
  throw new Error(`Unknown probe ${probe}`);
}

main();
