import path from "node:path";
export default { outputFileTracingRoot: path.resolve(import.meta.dirname), eslint: { ignoreDuringBuilds: true } };
