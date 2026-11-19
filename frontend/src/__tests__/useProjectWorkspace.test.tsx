import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { useProjectWorkspace } from "../hooks/useProjectWorkspace";
import { ApiError, RootPatchApiClient } from "../services/apiClient";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const res = (available: boolean) => ({
  state: available ? ("available" as const) : ("missing" as const),
  available,
});

function status(id: string, flags: Partial<Record<string, boolean>> = {}) {
  return {
    project_id: id,
    project_name: `proj-${id}`,
    project: res(true),
    structure: res(true),
    scan: res(flags.scan ?? false),
    analysis: res(flags.analysis ?? false),
    patches: res(flags.patches ?? false),
    validations: res(flags.validations ?? false),
    patch_counts: { total: 0, by_status: {} },
    can_analyze: true,
    can_generate_patches: flags.analysis ?? false,
  };
}

const project = (id: string) => ({ project_id: id, project_name: `proj-${id}` });

function makeClient(overrides: Record<string, unknown> = {}) {
  return {
    getHealth: vi.fn().mockResolvedValue({ status: "healthy" }),
    getProject: vi.fn().mockImplementation(async (id: string) => project(id)),
    getProjectStatus: vi.fn().mockImplementation(async (id: string) => status(id)),
    getProjectStructure: vi.fn().mockResolvedValue({ tree: {} }),
    getScan: vi.fn(),
    getAnalysis: vi.fn(),
    getPatches: vi.fn(),
    getPatchHistory: vi.fn(),
    getProjectValidations: vi.fn(),
    ...overrides,
  } as unknown as RootPatchApiClient & Record<string, ReturnType<typeof vi.fn>>;
}

describe("useProjectWorkspace request flow", () => {
  it("does not request analysis, patches, scan, history or validations when missing (StrictMode)", async () => {
    const client = makeClient();
    const wrapper = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;
    const { result } = renderHook(() => useProjectWorkspace("a", client), { wrapper });

    await waitFor(() => expect(result.current.project?.project_id).toBe("a"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(client.getAnalysis).not.toHaveBeenCalled();
    expect(client.getPatches).not.toHaveBeenCalled();
    expect(client.getScan).not.toHaveBeenCalled();
    expect(client.getPatchHistory).not.toHaveBeenCalled();
    expect(client.getProjectValidations).not.toHaveBeenCalled();
    // StrictMode's double effect shares one load
    expect(client.getProject).toHaveBeenCalledTimes(1);
    expect(client.getProjectStatus).toHaveBeenCalledTimes(1);
    expect(client.getProjectStructure).toHaveBeenCalledTimes(1);
    expect(client.getHealth).toHaveBeenCalledTimes(1);
    expect(result.current.analysis).toBeNull();
    expect(result.current.patches).toBeNull();
  });

  it("requests only the resources the status reports as available", async () => {
    const client = makeClient({
      getProjectStatus: vi
        .fn()
        .mockResolvedValue(status("a", { scan: true, analysis: true, patches: true })),
      getScan: vi.fn().mockResolvedValue({ project_id: "a", scan_id: "s" }),
      getAnalysis: vi.fn().mockResolvedValue({ project_id: "a", report_id: "r" }),
      getPatches: vi.fn().mockResolvedValue({ project_id: "a", patches: [] }),
      getPatchHistory: vi.fn().mockResolvedValue({ project_id: "a", history: [] }),
    });
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.analysis).not.toBeNull());

    expect(client.getScan).toHaveBeenCalledTimes(1);
    expect(client.getAnalysis).toHaveBeenCalledTimes(1);
    expect(client.getPatches).toHaveBeenCalledTimes(1);
    expect(client.getPatchHistory).toHaveBeenCalledTimes(1);
    expect(client.getProjectValidations).not.toHaveBeenCalled();
  });

  it("reports a genuinely missing project and requests nothing else", async () => {
    const err = () => new ApiError(404, "Project not found.", "project_not_found");
    const client = makeClient({
      getProject: vi.fn().mockRejectedValue(err()),
      getProjectStatus: vi.fn().mockRejectedValue(err()),
    });
    const { result } = renderHook(() => useProjectWorkspace("gone", client));
    await waitFor(() => expect(result.current.errorCode).toBe("project_not_found"));
    expect(result.current.project).toBeNull();
    expect(client.getProjectStructure).not.toHaveBeenCalled();
    expect(client.getAnalysis).not.toHaveBeenCalled();
  });

  it("surfaces a genuine failure of an available resource instead of hiding it as empty", async () => {
    const client = makeClient({
      getProjectStatus: vi.fn().mockResolvedValue(status("a", { analysis: true })),
      getAnalysis: vi.fn().mockRejectedValue(new ApiError(500, "Stored analysis results are corrupted or unreadable.", "analysis_error")),
    });
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.project?.project_id).toBe("a");
    expect(result.current.analysis).toBeNull();
    expect(result.current.resourceErrors.analysis).toMatch(/corrupted/i);
  });

  it("surfaces status-reported error state without requesting the broken resource", async () => {
    const client = makeClient({
      getProjectStatus: vi.fn().mockResolvedValue({
        ...status("a"),
        analysis: { state: "error", available: false, detail: "Stored analysis results are corrupted or unreadable." },
      }),
    });
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(client.getAnalysis).not.toHaveBeenCalled();
    expect(result.current.resourceErrors.analysis).toMatch(/corrupted/i);
  });

  it("falls back to tolerant probing against a legacy backend without /status", async () => {
    const client = makeClient({
      getProjectStatus: vi.fn().mockRejectedValue(new ApiError(404, "Not Found")),
      getScan: vi.fn().mockRejectedValue(new ApiError(404, "No scan results found for this project.", "scan_not_found")),
      getAnalysis: vi.fn().mockRejectedValue(new ApiError(404, "x", "analysis_not_found")),
      getPatches: vi.fn().mockRejectedValue(new ApiError(404, "x", "patches_not_found")),
      getPatchHistory: vi.fn().mockResolvedValue({ project_id: "a", history: [] }),
      getProjectValidations: vi.fn().mockResolvedValue({ project_id: "a", validations: [] }),
    });
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.project?.project_id).toBe("a");
    expect(result.current.error).toBeNull();
    expect(Object.keys(result.current.resourceErrors)).toHaveLength(0);
  });

  it("ignores a stale response from a previously selected project", async () => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    const client = makeClient({
      getProject: vi.fn().mockImplementation((id: string) => (id === "a" ? a.promise : b.promise)),
    });
    const { result, rerender } = renderHook(({ id }) => useProjectWorkspace(id, client), {
      initialProps: { id: "a" },
    });
    rerender({ id: "b" });

    await act(async () => {
      b.resolve(project("b"));
    });
    await waitFor(() => expect(result.current.project?.project_id).toBe("b"));

    await act(async () => {
      a.resolve(project("a")); // older request finishes last
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.project?.project_id).toBe("b");
    expect(result.current.loading).toBe(false);
  });

  it("drops results that belong to a different project than the active one", async () => {
    const client = makeClient();
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.project?.project_id).toBe("a"));

    act(() => {
      result.current.setAnalysis({ project_id: "other", report_id: "x" } as never);
    });
    expect(result.current.analysis).toBeNull();

    act(() => {
      result.current.setAnalysis({ project_id: "a", report_id: "y" } as never);
    });
    expect(result.current.analysis).not.toBeNull();
  });

  it("refreshes status after analysis completes", async () => {
    const client = makeClient();
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.project?.project_id).toBe("a"));
    expect(client.getProjectStatus).toHaveBeenCalledTimes(1);

    (client.getProjectStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      status("a", { scan: true, analysis: true })
    );
    act(() => {
      result.current.setAnalysis({ project_id: "a", report_id: "y" } as never);
    });
    await waitFor(() => expect(result.current.status?.analysis.available).toBe(true));
    expect(result.current.status?.can_generate_patches).toBe(true);
  });

  it("forced refresh reloads everything and supersedes an in-flight load", async () => {
    const client = makeClient();
    const { result } = renderHook(() => useProjectWorkspace("a", client));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.refreshAll();
    });
    expect(client.getProject).toHaveBeenCalledTimes(2);
  });
});
