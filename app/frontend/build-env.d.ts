// Minimal ambient types for the build tooling (vite.config.ts) so it can read the app-repo git
// short SHA without pulling the whole @types/node dependency. Only the single call the config
// uses is declared; everything else stays out of the frontend's type surface.
declare module "node:child_process" {
  export function execSync(
    command: string,
    options?: { stdio?: Array<"ignore" | "pipe" | "inherit">; encoding?: string },
  ): { toString(): string };
}
