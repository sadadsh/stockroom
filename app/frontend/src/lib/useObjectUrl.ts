import { useEffect, useState } from "react";

/**
 * Turn a fetched Blob into an object URL for an <img>/loader src, revoking it when the
 * blob changes or the component unmounts so the browser never leaks the backing memory
 * (the preview viewer swaps blobs as the user switches parts and tabs).
 */
export function useObjectUrl(blob: Blob | undefined | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}
