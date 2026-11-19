import type {
  AnalysisReportResponse,
  HealthResponse,
  PatchApplicationHistoryResponse,
  PatchApplyResponse,
  PatchBatchResponse,
  PatchGenerateRequest,
  PatchRecord,
  PatchReviewDecisionRequest,
  PatchReviewResponse,
  ProjectMetadata,
  RootCauseAnalysisItem,
  ScanResponse,
  StructureResponse,
  UploadResponse,
  ValidationHistoryListResponse,
  ValidationReportResponse,
  ValidationRunRequest,
} from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (configured && configured.trim()) {
    return configured.trim().replace(/\/+$/, "");
  }
  return "http://localhost:8000";
}

function buildUrl(path: string, baseUrl = getApiBaseUrl()): string {
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof data?.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
    if (Array.isArray(data?.detail) && data.detail.length > 0) {
      const first = data.detail[0] as { msg?: string };
      if (first?.msg) {
        return first.msg;
      }
    }
    if (typeof data?.message === "string" && data.message.trim()) {
      return data.message;
    }
  } catch {
    // Non-JSON error body
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  baseUrl?: string
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, baseUrl), {
      ...init,
      headers: {
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(init.headers || {}),
      },
    });
  } catch (err) {
    throw new ApiError(
      0,
      err instanceof Error
        ? `Unable to reach backend API (${err.message}).`
        : "Unable to reach backend API."
    );
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export class RootPatchApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = getApiBaseUrl()) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  getHealth(): Promise<HealthResponse> {
    return requestJson<HealthResponse>("/api/health", { method: "GET" }, this.baseUrl);
  }

  uploadProject(
    file: File,
    onProgress?: (percent: number) => void
  ): Promise<UploadResponse> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", buildUrl("/api/projects/upload", this.baseUrl));

      xhr.upload.onprogress = (event) => {
        if (onProgress && event.lengthComputable && event.total > 0) {
          const pct = Math.min(100, Math.round((event.loaded / event.total) * 100));
          onProgress(pct);
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as UploadResponse);
          } catch {
            reject(new ApiError(xhr.status, "Invalid JSON returned by upload endpoint."));
          }
          return;
        }
        let detail = xhr.statusText || `Upload failed with status ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
            detail = parsed.detail;
          }
        } catch {
          // ignore non-JSON body
        }
        reject(new ApiError(xhr.status, detail));
      };

      xhr.onerror = () => {
        reject(new ApiError(0, "Network error while uploading archive to backend."));
      };

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    });
  }

  getProject(projectId: string): Promise<ProjectMetadata> {
    return requestJson<ProjectMetadata>(
      `/api/projects/${encodeURIComponent(projectId)}`,
      { method: "GET" },
      this.baseUrl
    );
  }

  getProjectStructure(projectId: string): Promise<StructureResponse> {
    return requestJson<StructureResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/structure`,
      { method: "GET" },
      this.baseUrl
    );
  }

  runScan(projectId: string): Promise<ScanResponse> {
    return requestJson<ScanResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/scan`,
      { method: "POST" },
      this.baseUrl
    );
  }

  getScan(projectId: string): Promise<ScanResponse> {
    return requestJson<ScanResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/scan`,
      { method: "GET" },
      this.baseUrl
    );
  }

  runAnalysis(projectId: string): Promise<AnalysisReportResponse> {
    return requestJson<AnalysisReportResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/analyze`,
      { method: "POST" },
      this.baseUrl
    );
  }

  getAnalysis(projectId: string): Promise<AnalysisReportResponse> {
    return requestJson<AnalysisReportResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/analysis`,
      { method: "GET" },
      this.baseUrl
    );
  }

  getAnalysisItem(projectId: string, analysisId: string): Promise<RootCauseAnalysisItem> {
    return requestJson<RootCauseAnalysisItem>(
      `/api/projects/${encodeURIComponent(projectId)}/analysis/${encodeURIComponent(analysisId)}`,
      { method: "GET" },
      this.baseUrl
    );
  }

  generatePatches(
    projectId: string,
    payload?: PatchGenerateRequest
  ): Promise<PatchBatchResponse> {
    return requestJson<PatchBatchResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/generate`,
      {
        method: "POST",
        body: payload ? JSON.stringify(payload) : undefined,
      },
      this.baseUrl
    );
  }

  getPatches(projectId: string): Promise<PatchBatchResponse> {
    return requestJson<PatchBatchResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches`,
      { method: "GET" },
      this.baseUrl
    );
  }

  getPatch(projectId: string, patchId: string): Promise<PatchRecord> {
    return requestJson<PatchRecord>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}`,
      { method: "GET" },
      this.baseUrl
    );
  }

  getPatchReview(projectId: string, patchId: string): Promise<PatchReviewResponse> {
    return requestJson<PatchReviewResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}/review`,
      { method: "GET" },
      this.baseUrl
    );
  }

  approvePatch(
    projectId: string,
    patchId: string,
    payload?: PatchReviewDecisionRequest
  ): Promise<PatchRecord> {
    return requestJson<PatchRecord>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}/approve`,
      {
        method: "POST",
        body: payload ? JSON.stringify(payload) : undefined,
      },
      this.baseUrl
    );
  }

  rejectPatch(
    projectId: string,
    patchId: string,
    payload?: PatchReviewDecisionRequest
  ): Promise<PatchRecord> {
    return requestJson<PatchRecord>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}/reject`,
      {
        method: "POST",
        body: payload ? JSON.stringify(payload) : undefined,
      },
      this.baseUrl
    );
  }

  applyPatch(projectId: string, patchId: string): Promise<PatchApplyResponse> {
    return requestJson<PatchApplyResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}/apply`,
      { method: "POST" },
      this.baseUrl
    );
  }

  getPatchHistory(projectId: string): Promise<PatchApplicationHistoryResponse> {
    return requestJson<PatchApplicationHistoryResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/history`,
      { method: "GET" },
      this.baseUrl
    );
  }

  validatePatch(
    projectId: string,
    patchId: string,
    payload?: ValidationRunRequest
  ): Promise<ValidationReportResponse> {
    return requestJson<ValidationReportResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}/validate`,
      {
        method: "POST",
        body: payload ? JSON.stringify(payload) : undefined,
      },
      this.baseUrl
    );
  }

  getPatchValidations(
    projectId: string,
    patchId: string
  ): Promise<ValidationHistoryListResponse> {
    return requestJson<ValidationHistoryListResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/patches/${encodeURIComponent(patchId)}/validations`,
      { method: "GET" },
      this.baseUrl
    );
  }

  getProjectValidations(projectId: string): Promise<ValidationHistoryListResponse> {
    return requestJson<ValidationHistoryListResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/validations`,
      { method: "GET" },
      this.baseUrl
    );
  }

  getValidationReport(
    projectId: string,
    validationId: string
  ): Promise<ValidationReportResponse> {
    return requestJson<ValidationReportResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/validations/${encodeURIComponent(validationId)}`,
      { method: "GET" },
      this.baseUrl
    );
  }
}

export const apiClient = new RootPatchApiClient();
