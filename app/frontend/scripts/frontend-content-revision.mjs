import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

export const DEFAULT_FRONTEND_BUILD_INPUTS = Object.freeze([
  "build-env.d.ts",
  "index.html",
  "package-lock.json",
  "package.json",
  "postcss.config.js",
  "public",
  "scripts",
  "src",
  "tailwind.config.js",
  "tsconfig.app.json",
  "tsconfig.json",
  "tsconfig.node.json",
  "vite.config.ts",
]);

const DEVELOPMENT_BUILD_ENVIRONMENT = Object.freeze([
  "STOCKROOM_DEV_BOOTSTRAP",
  "STOCKROOM_DEV_BACKEND_URL",
  "STOCKROOM_DEV_ENV_DIR",
  "VITE_API_BASE",
  "VITE_API_TOKEN",
]);

/** A committed production bundle never inherits workstation-only development configuration. */
export function assertProductionBuildEnvironment(environment = process.env) {
  for (const name of DEVELOPMENT_BUILD_ENVIRONMENT) {
    if (String(environment[name] ?? "").trim()) {
      throw new Error(`${name} is not allowed during a production frontend build`);
    }
  }
}

function filesBelow(root, relative) {
  const absolute = path.join(root, relative);
  const stats = statSync(absolute, { throwIfNoEntry: false });
  if (!stats) throw new Error(`frontend build input does not exist: ${relative}`);
  if (stats.isFile()) return [relative.replaceAll("\\", "/")];
  if (!stats.isDirectory()) throw new Error(`frontend build input is not a file or directory: ${relative}`);
  return readdirSync(absolute, { withFileTypes: true })
    .sort((left, right) => left.name.localeCompare(right.name, "en"))
    .flatMap((entry) => filesBelow(root, path.join(relative, entry.name)));
}

/** Stable identity for every declared input that can change the committed web distribution. */
export function frontendContentRevision(frontendRoot, inputs = DEFAULT_FRONTEND_BUILD_INPUTS) {
  const root = path.resolve(frontendRoot);
  const files = [...new Set(inputs.flatMap((input) => filesBelow(root, input)))].sort();
  const hash = createHash("sha256");
  for (const relative of files) {
    hash.update(relative, "utf8");
    hash.update(Uint8Array.of(0));
    hash.update(readFileSync(path.join(root, relative)));
    hash.update(Uint8Array.of(0));
  }
  return hash.digest("hex").slice(0, 12);
}
