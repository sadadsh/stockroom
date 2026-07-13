import { act, renderHook } from "@testing-library/react";
import { api } from "../api/client";
import { useJob } from "./useJob";

vi.mock("../api/client", async (im) => {
  const actual = await im<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, openJobStream: vi.fn() } };
});
const mockApi = vi.mocked(api);

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

describe("useJob", () => {
  it("streams progress then the result into state", async () => {
    mockApi.openJobStream.mockResolvedValue(
      streamOf([
        'event: progress\ndata: {"pct":50,"message":"unpacking"}\n\n',
        'event: result\ndata: {"result":[{"mpn":"LM358"}]}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const { result } = renderHook(() => useJob<Array<{ mpn: string }>>());

    await act(async () => {
      await result.current.run("job123");
    });

    expect(result.current.status).toBe("done");
    expect(result.current.result).toEqual([{ mpn: "LM358" }]);
  });

  it("surfaces a job error event as an error state", async () => {
    mockApi.openJobStream.mockResolvedValue(
      streamOf([
        'event: error\ndata: {"detail":"unpack failed","error":"IngestError"}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const { result } = renderHook(() => useJob());

    await act(async () => {
      await result.current.run("j");
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("unpack failed");
  });

  it("surfaces a stream-open failure honestly", async () => {
    mockApi.openJobStream.mockRejectedValue(new Error("connection refused"));
    const { result } = renderHook(() => useJob());

    await act(async () => {
      await result.current.run("j");
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("connection refused");
  });
});
