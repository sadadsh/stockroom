// Minimal ambient types for the build tooling. Resolving the frontend root and pdf.js's
// `standard_fonts` directory needs only these calls, so the browser type surface does not pull in
// the complete Node declarations.
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

declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
  export class URL {
    constructor(input: string);
    readonly protocol: string;
    readonly hostname: string;
    readonly username: string;
    readonly password: string;
    readonly pathname: string;
    readonly search: string;
    readonly hash: string;
    readonly origin: string;
  }
}

declare const process: {
  readonly env: Record<string, string | undefined>;
};

interface ImportMeta {
  readonly url: string;
}
