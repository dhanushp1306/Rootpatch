import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, RootPatchApiClient, apiClient as defaultClient } from "../services/apiClient";
import type {
  AnalysisReportResponse,
  HealthResponse,
  PatchApplicationHistoryResponse,
  PatchBatchResponse,
  ProjectMetadata,
  ProjectStatusResponse,
  ScanResponse,
  StructureResponse,
  ValidationHistoryListResponse,
} from "../types/api";

export interface WorkspaceState {
  health: HealthResponse | null;
  healthError: string | null;
  project: ProjectMetadata | null;
  /** Server-reported availability of optional resources for the active project. */
  status: ProjectStatusResponse | null;
  structure: StructureResponse | null;
  scan: ScanResponse | null;
  analysis: AnalysisReportResponse | null;
  patches: PatchBatchResponse | null;
  patchHistory: PatchApplicationHistoryResponse | null;
  validations: ValidationHistoryListResponse | null;
  /** Per-resource load failures for stored data that exists but could not be read. */
  resourceErrors: Record<string, string>;
  loading: boolean;
  error: string | null;
  /** Machine-readable code for `error` (e.g. "project_not_found"). */
  errorCode: string | null;
}

const EMPTY_DATA = {
  project: null,
  status: null,
  structure: null,
  scan: null,
  analysis: null,
  patches: null,
  patchHistory: null,
  validations: null,
  resourceErrors: {} as Record<string, string>,
};

const INITIAL_STATE: WorkspaceState = {
  health: null,
  healthError: null,
  ...EMPTY_DATA,
  loading: false,
  error: null,
  errorCode: null,
};

/** A 404 for an optional resource that the status call said was available (race/legacy backend). */
function isResourceMissing(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && err.code !== "project_not_found";
}

async function fetchOptional<T>(
  key: string,
  fn: () => Promise<T>,
  errors: Record<string, string>
): Promise<T | null> {
  try {
    return await fn();
  } catch (err) {
    if (isResourceMissing(err)) {
      return null;
    }
    if (err instanceof ApiError && err.code === "project_not_found") {
      throw err;
    }
    errors[key] = err instanceof ApiError ? err.detail : `Failed to load ${key}.`;
    return null;
  }
}

export function useProjectWorkspace(
  projectId: string | null,
  client: RootPatchApiClient = defaultClient
) {
  const [state, setState] = useState<WorkspaceState>(INITIAL_STATE);

  // Monotonic token: only the most recently started load may write state.
  const tokenRef = useRef(0);
  // In-flight load per project; lets React StrictMode's double effect share one load.
  const inflightRef = useRef<{ projectId: string; promise: Promise<void> } | null>(null);
  // Project whose data is currently held in state.
  const loadedProjectRef = useRef<string | null>(null);
  const projectIdRef = useRef<string | null>(projectId);
  projectIdRef.current = projectId;

  const healthInflightRef = useRef<Promise<void> | null>(null);

  const refreshHealth = useCallback((): Promise<void> => {
    if (healthInflightRef.current) {
      return healthInflightRef.current;
    }
    const promise = (async () => {
      try {
        const health = await client.getHealth();
        setState((prev) => ({ ...prev, health, healthError: null }));
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : "Backend unreachable.";
        setState((prev) => ({ ...prev, health: null, healthError: msg }));
      }
    })().finally(() => {
      healthInflightRef.current = null;
    });
    healthInflightRef.current = promise;
    return promise;
  }, [client]);

  const load = useCallback(
    (force: boolean): Promise<void> => {
      if (!projectId) {
        tokenRef.current += 1;
        inflightRef.current = null;
        loadedProjectRef.current = null;
        setState((prev) => ({
          ...prev,
          ...EMPTY_DATA,
          loading: false,
          error: null,
          errorCode: null,
        }));
        return Promise.resolve();
      }

      const inflight = inflightRef.current;
      if (!force && inflight && inflight.projectId === projectId) {
        return inflight.promise;
      }

      const token = ++tokenRef.current;
      const isCurrent = () => token === tokenRef.current;
      const switchingProject = loadedProjectRef.current !== projectId;

      setState((prev) => ({
        ...prev,
        ...(switchingProject ? EMPTY_DATA : {}),
        loading: true,
        error: null,
        errorCode: null,
      }));

      const run = async () => {
        try {
          // Project details and status are the only unconditional requests.
          const [project, status] = await loadProjectAndStatus(client, projectId);
          if (!isCurrent()) return;

          const errors: Record<string, string> = {};
          for (const [key, res] of Object.entries({
            structure: status?.structure,
            scan: status?.scan,
            analysis: status?.analysis,
            patches: status?.patches,
            validations: status?.validations,
          })) {
            if (res?.state === "error") {
              errors[key] = res.detail || `Stored ${key} data could not be read.`;
            }
          }

          // Optional resources are requested only when the server says they exist.
          // Without a status (legacy backend), fall back to probing with 404 tolerance.
          const want = (res: { available: boolean } | undefined) =>
            status ? res?.available === true : true;

          const [structure, scan, analysis, patches, validations] = await Promise.all([
            want(status?.structure)
              ? fetchOptional("structure", () => client.getProjectStructure(projectId), errors)
              : null,
            want(status?.scan)
              ? fetchOptional("scan", () => client.getScan(projectId), errors)
              : null,
            want(status?.analysis)
              ? fetchOptional("analysis", () => client.getAnalysis(projectId), errors)
              : null,
            want(status?.patches)
              ? fetchOptional("patches", () => client.getPatches(projectId), errors)
              : null,
            want(status?.validations)
              ? fetchOptional("validations", () => client.getProjectValidations(projectId), errors)
              : null,
          ]);
          if (!isCurrent()) return;

          // Application history only exists once patches were generated.
          const patchHistory = want(status?.patches)
            ? await fetchOptional("patch history", () => client.getPatchHistory(projectId), errors)
            : null;
          if (!isCurrent()) return;

          loadedProjectRef.current = projectId;
          setState((prev) => ({
            ...prev,
            project,
            status,
            structure,
            scan,
            analysis,
            patches,
            patchHistory,
            validations,
            resourceErrors: errors,
            loading: false,
            error: null,
            errorCode: null,
          }));
        } catch (err) {
          if (!isCurrent()) return;
          const isApi = err instanceof ApiError;
          const notFound = isApi && err.code === "project_not_found";
          const message = notFound
            ? "This project could not be found on the backend. It may have been deleted, or the backend is using a different workspace."
            : isApi
              ? err.detail
              : err instanceof Error
                ? err.message
                : "Failed to load project workspace.";
          setState((prev) => ({
            ...prev,
            ...(notFound ? EMPTY_DATA : {}),
            loading: false,
            error: message,
            errorCode: isApi ? (err.code ?? (err.status === 404 ? "project_not_found" : null)) : null,
          }));
        }
      };

      const promise: Promise<void> = run().finally(() => {
        if (inflightRef.current?.promise === promise) {
          inflightRef.current = null;
        }
      });
      inflightRef.current = { projectId, promise };
      return promise;
    },
    [client, projectId]
  );

  // Normal (non-forced) load on mount / project switch; StrictMode double-invoke is deduped.
  useEffect(() => {
    void load(false);
  }, [load]);

  // Health is independent of the project and only checked on mount / client change.
  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  /** Forced full reload of the active project (manual refresh, after apply/validate). */
  const refreshAll = useCallback(async () => {
    void refreshHealth();
    await load(true);
  }, [load, refreshHealth]);

  /** Re-read only the lightweight status document. */
  const refreshStatus = useCallback(async () => {
    const id = projectIdRef.current;
    if (!id) return;
    try {
      const status = await client.getProjectStatus(id);
      if (projectIdRef.current === id) {
        setState((prev) => (prev.project?.project_id === id ? { ...prev, status } : prev));
      }
    } catch {
      // Status is advisory; a failure here must not break already-loaded data.
    }
  }, [client]);

  const belongsToActiveProject = (resourceProjectId: string) =>
    projectIdRef.current !== null && resourceProjectId === projectIdRef.current;

  const setScan = useCallback(
    (scan: ScanResponse) => {
      if (!belongsToActiveProject(scan.project_id)) return;
      setState((prev) => ({ ...prev, scan }));
      void refreshStatus();
    },
    [refreshStatus]
  );

  const setAnalysis = useCallback(
    (analysis: AnalysisReportResponse) => {
      if (!belongsToActiveProject(analysis.project_id)) return;
      setState((prev) => ({ ...prev, analysis }));
      void refreshStatus();
    },
    [refreshStatus]
  );

  const setPatches = useCallback(
    (patches: PatchBatchResponse) => {
      if (!belongsToActiveProject(patches.project_id)) return;
      setState((prev) => ({ ...prev, patches }));
      void refreshStatus();
    },
    [refreshStatus]
  );

  return {
    ...state,
    refreshAll,
    refreshHealth,
    refreshStatus,
    setScan,
    setAnalysis,
    setPatches,
  };
}

async function loadProjectAndStatus(
  client: RootPatchApiClient,
  projectId: string
): Promise<[ProjectMetadata, ProjectStatusResponse | null]> {
  const [project, status] = await Promise.all([
    client.getProject(projectId),
    client.getProjectStatus(projectId).catch((err: unknown) => {
      // Older backends without /status: fall back to tolerant probing.
      if (err instanceof ApiError && err.status === 404 && err.code === null) {
        return null;
      }
      throw err;
    }),
  ]);
  return [project, status];
}
