// Minimal ambient types for the build tooling (vite.config.ts) so it can read the app-repo git
// short SHA without pulling the whole @types/node dependency. Only the single call the config
// uses is declared; everything else stays out of the frontend's type surface.
declare module "node:child_process" {
  export function execSync(
    command: string,
    options?: { stdio?: Array<"ignore" | "pipe" | "inherit">; encoding?: string },
  ): { toString(): string };
}

// Resolving pdf.js's `standard_fonts` directory needs exactly three more calls: joining a path,
// taking its directory, and asking the module resolver where a package lives. Declared here for
// the same reason as the above - the build tooling gets what it uses and the frontend's own type
// surface stays free of Node.
declare module "node:path" {
  export function join(...parts: string[]): string;
  export function dirname(target: string): string;
  const path: { join: typeof join; dirname: typeof dirname };
  export default path;
}

declare module "node:module" {
  export function createRequire(from: string | URL): {
    resolve(request: string): string;
  };
}

interface ImportMeta {
  readonly url: string;
}
