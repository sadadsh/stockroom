import { guardPreviewEffect } from "../design-studio/previewEffects";

export function openExternalUrl(url: string): Window | null {
  guardPreviewEffect({
    kind: "external-navigation",
    action: "opening an external page",
    instruction: "open this page",
  });
  return window.open(url, "_blank", "noreferrer");
}
