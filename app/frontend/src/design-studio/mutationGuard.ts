import type { ApiRequestDescriptor } from "./requestAdapter";

export type PreviewRequestClassification = "studio-live" | "fixture-only" | "block";

const READ_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export class PreviewMutationError extends Error {
  readonly descriptor: ApiRequestDescriptor;

  constructor(descriptor: ApiRequestDescriptor) {
    super(
      `Preview blocked ${descriptor.method.toUpperCase()} ${descriptor.path}. ` +
        "Exit fixture preview and return to Real Data to perform this action.",
    );
    this.name = "PreviewMutationError";
    this.descriptor = descriptor;
  }
}

/** Classifies requests only after explicit scenario fixtures have had first refusal. */
export function classifyPreviewRequest(
  descriptor: ApiRequestDescriptor,
): PreviewRequestClassification {
  const method = descriptor.method.toUpperCase();
  if (
    ((descriptor.path === "/api/design-studio/personal" && (method === "GET" || method === "PUT")) ||
      (descriptor.path === "/api/design-studio/personal/page-exit" && method === "PUT"))
  ) return "studio-live";
  return READ_METHODS.has(method) ? "fixture-only" : "block";
}

export function guardPreviewRequest(
  descriptor: ApiRequestDescriptor,
): Exclude<PreviewRequestClassification, "block"> {
  const classification = classifyPreviewRequest(descriptor);
  if (classification === "block") throw new PreviewMutationError(descriptor);
  return classification;
}
