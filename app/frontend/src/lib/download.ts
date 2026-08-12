import { guardPreviewEffect } from "../design-studio/previewEffects";

export function downloadBlob(filename: string, blob: Blob): void {
  guardPreviewEffect({
    kind: "download",
    action: `downloading ${filename}`,
    instruction: "download this file",
  });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
