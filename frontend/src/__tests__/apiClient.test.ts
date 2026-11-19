import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, RootPatchApiClient } from "../services/apiClient";

describe("RootPatchApiClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("constructs endpoints and sends JSON payloads cleanly", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "healthy", app: "RootPatch", version: "0.1.0", message: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new RootPatchApiClient("http://localhost:8000/");
    const health = await client.getHealth();

    expect(health.status).toBe("healthy");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/health",
      expect.objectContaining({ method: "GET" })
    );

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ batch_id: "b1", patches: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await client.generatePatches("proj123", { finding_id: "f1", analysis_id: "a1" });
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/api/projects/proj123/patches/generate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ finding_id: "f1", analysis_id: "a1" }),
      })
    );
  });

  it("parses backend FastAPI detail strings into ApiError", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "Patch must be applied before validation." }),
        { status: 409, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new RootPatchApiClient("http://localhost:8000");

    await expect(client.validatePatch("p1", "patch1")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      detail: "Patch must be applied before validation.",
    });
  });

  it("wraps network failures in ApiError with status 0", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const client = new RootPatchApiClient("http://localhost:8000");
    await expect(client.getProject("p1")).rejects.toBeInstanceOf(ApiError);
  });

  it("uploads multipart archive via XHR and reports progress", async () => {
    const progressEvents: number[] = [];

    class MockXHR {
      upload: { onprogress?: (ev: ProgressEvent) => void } = {};
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      status = 201;
      statusText = "Created";
      responseText = JSON.stringify({
        project_id: "a".repeat(32),
        project_name: "demo",
        status: "ready",
        message: "Project uploaded and inspected.",
      });
      method = "";
      url = "";
      sentBody: unknown = null;

      open(method: string, url: string) {
        this.method = method;
        this.url = url;
      }

      send(body: unknown) {
        this.sentBody = body;
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 50,
          total: 100,
        } as ProgressEvent);
        this.onload?.();
      }
    }

    vi.stubGlobal("XMLHttpRequest", MockXHR);

    const client = new RootPatchApiClient("http://localhost:8000");
    const file = new File(["zipdata"], "demo.zip", { type: "application/zip" });
    const res = await client.uploadProject(file, (pct) => progressEvents.push(pct));

    expect(res.project_id).toBe("a".repeat(32));
    expect(progressEvents).toEqual([50]);
  });
});
