import { useCallback, useEffect, useState } from "react";
import { ApiError, RootPatchApiClient, apiClient as defaultClient } from "../services/apiClient";
import type {
  AnalysisReportResponse,
  HealthResponse,
  PatchApplicationHistoryResponse,
  PatchBatchResponse,
  ProjectMetadata,
  ScanResponse,
  StructureResponse,
  ValidationHistoryListResponse,
} from "../types/api";

export interface WorkspaceState {
  health: HealthResponse | null;
  healthError: string | null;
  project: ProjectMetadata | null;
  structure: StructureResponse | null;
  scan: ScanResponse | null;
  analysis: AnalysisReportResponse | null;
  patches: PatchBatchResponse | null;
  patchHistory: PatchApplicationHistoryResponse | null;
  validations: ValidationHistoryListResponse | null;
  loading: boolean;
  error: string | null;
}

async function optionalGet<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export function useProjectWorkspace(
  projectId: string | null,
  client: RootPatchApiClient = defaultClient
) {
  const [state, setState] = useState<WorkspaceState>({
    health: null,
    healthError: null,
    project: null,
    structure: null,
    scan: null,
    analysis: null,
    patches: null,
    patchHistory: null,
    validations: null,
    loading: false,
    error: null,
  });

  const refreshHealth = useCallback(async () => {
    try {
      const health = await client.getHealth();
      setState((prev) => ({ ...prev, health, healthError: null }));
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Backend unreachable.";
      setState((prev) => ({ ...prev, health: null, healthError: msg }));
    }
  }, [client]);

  const refreshAll = useCallback(async () => {
    void refreshHealth();
    if (!projectId) {
      setState((prev) => ({
        ...prev,
        project: null,
        structure: null,
        scan: null,
        analysis: null,
        patches: null,
        patchHistory: null,
        validations: null,
        loading: false,
        error: null,
      }));
      return;
    }

    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const project = await client.getProject(projectId);
      const [structure, scan, analysis, patches, patchHistory, validations] =
        await Promise.all([
          optionalGet(() => client.getProjectStructure(projectId)),
          optionalGet(() => client.getScan(projectId)),
          optionalGet(() => client.getAnalysis(projectId)),
          optionalGet(() => client.getPatches(projectId)),
          optionalGet(() => client.getPatchHistory(projectId)),
          optionalGet(() => client.getProjectValidations(projectId)),
        ]);

      setState((prev) => ({
        ...prev,
        project,
        structure,
        scan,
        analysis,
        patches,
        patchHistory,
        validations,
        loading: false,
        error: null,
      }));
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Failed to load project workspace.";
      setState((prev) => ({
        ...prev,
        loading: false,
        error: message,
      }));
    }
  }, [client, projectId, refreshHealth]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const setScan = useCallback((scan: ScanResponse) => {
    setState((prev) => ({ ...prev, scan }));
  }, []);

  const setAnalysis = useCallback((analysis: AnalysisReportResponse) => {
    setState((prev) => ({ ...prev, analysis }));
  }, []);

  const setPatches = useCallback((patches: PatchBatchResponse) => {
    setState((prev) => ({ ...prev, patches }));
  }, []);

  return {
    ...state,
    refreshAll,
    refreshHealth,
    setScan,
    setAnalysis,
    setPatches,
  };
}
