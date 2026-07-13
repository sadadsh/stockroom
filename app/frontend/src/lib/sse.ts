/**
 * Parse a fetch Response body (a byte ReadableStream) into Server-Sent Events.
 * The backend streams job progress here (stockroom.api.jobs): each frame is
 * `event: <kind>\ndata: <json>` separated by a blank line, terminated by a `done`
 * event. Native EventSource cannot send the bearer token, so the frontend reads
 * the stream through fetch + this parser instead (spec: token is header-only).
 */

export interface SSEEvent {
  event: string;
  data: unknown;
}

function parseFrame(frame: string): SSEEvent | null {
  if (!frame.trim()) return null;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (dataLines.length === 0) return null;
  const raw = dataLines.join("\n");
  let data: unknown = raw;
  try {
    data = JSON.parse(raw);
  } catch {
    // A non-JSON data line stays a raw string rather than crashing the stream.
  }
  return { event, data };
}

export async function* streamEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    // Frames are separated by a blank line ("\n\n"); emit each complete one.
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const ev = parseFrame(frame);
      if (ev) yield ev;
    }
  }
  const tail = parseFrame(buffer);
  if (tail) yield tail;
}
