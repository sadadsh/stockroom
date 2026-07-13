import { streamEvents } from "./sse";

// Build a ReadableStream of UTF-8 bytes from string chunks, so a test can feed
// exactly the byte boundaries the parser must tolerate (SSE frames split across
// network chunks).
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out: Array<{ event: string; data: unknown }> = [];
  for await (const ev of streamEvents(stream)) out.push(ev);
  return out;
}

describe("streamEvents", () => {
  it("parses named events with JSON data in order", async () => {
    const body = streamOf([
      'event: progress\ndata: {"pct":5,"message":"unpacking"}\n\n',
      'event: result\ndata: {"result":[{"mpn":"LM358"}]}\n\n',
      "event: done\ndata: {}\n\n",
    ]);
    const events = await collect(body);
    expect(events).toEqual([
      { event: "progress", data: { pct: 5, message: "unpacking" } },
      { event: "result", data: { result: [{ mpn: "LM358" }] } },
      { event: "done", data: {} },
    ]);
  });

  it("reassembles a frame that is split across chunks", async () => {
    const body = streamOf(["event: progress\nda", 'ta: {"pct":50}\n', "\n"]);
    const events = await collect(body);
    expect(events).toEqual([{ event: "progress", data: { pct: 50 } }]);
  });

  it("keeps non-JSON data as a raw string instead of throwing", async () => {
    const body = streamOf(["event: error\ndata: boom\n\n"]);
    const events = await collect(body);
    expect(events).toEqual([{ event: "error", data: "boom" }]);
  });
});
